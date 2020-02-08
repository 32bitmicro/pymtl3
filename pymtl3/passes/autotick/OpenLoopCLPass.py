"""
#=========================================================================
# OpenLoopCLPass.py
#=========================================================================
# Generate a simple schedule (no Mamba techniques here) based on the
# DAG generated by some previous pass.
#
# Author : Shunning Jiang
# Date   : Apr 20, 2019
"""
import os
import random
from collections import deque

import py

from pymtl3.datatypes import Bits1
from pymtl3.dsl import CalleeIfcCL, CalleePort
from pymtl3.dsl.errors import UpblkCyclicError

from ..BasePass import BasePass, PassMetadata
from ..errors import PassOrderError
from ..sim.SimpleSchedulePass import SimpleSchedulePass, dump_dag
from ..sim.SimpleTickPass import SimpleTickPass
from ..tracing.CLLineTracePass import CLLineTracePass
from ..tracing.CollectSignalPass import CollectSignalPass
from ..tracing.PrintWavePass import PrintWavePass
from ..tracing.VcdGenerationPass import VcdGenerationPass

random.seed(0xdeadbeef)

class OpenLoopCLPass( BasePass ):
  def __init__( self, print_line_trace=True ):
    self.line_trace_on = print_line_trace

  def __call__( self, top ):
    if not hasattr( top._dag, "all_constraints" ):
      raise PassOrderError( "all_constraints" )

    top._sched = PassMetadata()

    self.schedule_with_top_level_callee( top )

  def schedule_with_top_level_callee( self, top ):

    # Construct the graph with top level callee port
    V = top._dag.final_upblks - top.get_all_update_ff()
    E = set()

    # We collect all top level callee ports/nonblocking callee interfaces
    top_level_callee_ports = top.get_all_object_filter(
      lambda x: isinstance(x, CalleePort) and x.get_host_component() is top )

    top_level_nb_ifcs = top.get_all_object_filter(
      lambda x: isinstance(x, CalleeIfcCL) and x.get_host_component() is top )

    method_callee_mapping = {}
    method_guard_mapping  = {}
    guard_method_mapping  = {}

    def get_raw_method( x ):
      assert isinstance( x, CalleePort )
      return x.method

    # First deal with normal calleeports. We map the actual method to the
    # callee port, and add the port to the vertex set
    for x in top_level_callee_ports:
      if not x.in_non_blocking_interface(): # Normal callee port
        V.add(x)
        m = get_raw_method( x )
        assert m not in method_callee_mapping
        method_callee_mapping[m] = x

    # Then deal with non-blocking callee interfaces. Map the method of the
    # interface to the actual method and set up method-rdy mapping
    for x in top_level_nb_ifcs:
      V.add( x.method )
      V.add( x.rdy )
      E.add( (x.rdy, x.method) )

      method_guard_mapping[x.method] = x.rdy
      guard_method_mapping[x.rdy] = x.method
      m = get_raw_method( x.method )
      r = get_raw_method( x.rdy )

      assert m not in method_callee_mapping
      method_callee_mapping[m] = x.method
      method_callee_mapping[r] = x.rdy

    G   = { v: [] for v in V }
    G_T = { v: [] for v in V }

    for (u, v) in top._dag.all_constraints:
      if u in V and v in V:
        E.add( (u, v) )
        G  [u].append( v )
        G_T[v].append( u )

    # In addition to existing constraints, we process the constraints that
    # involve top level callee ports. NOTE THAT we assume the user never
    # set the constraint on the actual method object inside the CalleePort
    # In GenDAGPass we already collect those constraints between update
    # blocks and ACTUAL METHODs. We use the ACTUAL METHOD to callee
    # mapping we set up above to avoid missing constraints.

    for (xx, yy) in top._dag.top_level_callee_constraints:

      if xx in method_callee_mapping:
        xx = method_callee_mapping[ xx ]

      if yy in method_callee_mapping:
        yy = method_callee_mapping[ yy ]

      # if there is a constraint A<B, it means M(A.method) < B.rdy or means U(A) < B.rdy
      if yy in method_guard_mapping:
        yy = method_guard_mapping[ yy ]

      if xx in V and yy in V:
        E.add( (xx, yy) )
        G  [xx].append( yy )
        G_T[yy].append( xx )

    if 'MAMBA_DAG' in os.environ:
      dump_dag( top, V, E )

    #---------------------------------------------------------------------
    # Run Kosaraju's algorithm to shrink all strongly connected components
    # (SCCs) into super nodes
    #---------------------------------------------------------------------
    # See passes/sim/DynamicSchedulePass.py
    # TODO refactor this

    PO = []

    vertices = list(G.keys())
    random.shuffle(vertices)
    visited = set()

    for u in vertices:
      stack = [ (u, False) ]
      while stack:
        u, second_visit = stack.pop()

        if second_visit:
          PO.append( u )
        elif u not in visited:
          visited.add( u )
          stack.append( (u, True) )
          for v in reversed(G[u]):
            stack.append( (v, False) )

    RPO = PO[::-1]

    # Second bfs on G_T to generate SCCs

    SCCs  = []
    v_SCC = {}
    visited = set()

    for u in RPO:
      if u not in visited:
        visited.add( u )
        scc = set()
        SCCs.append( scc )
        Q = deque( [u] )
        scc.add( u )
        while Q:
          u = Q.popleft()
          v_SCC[u] = len(SCCs) - 1
          for v in G_T[u]:
            if v not in visited:
              visited.add( v )
              Q.append( v )
              scc.add( v )

    # Construct a new graph of SCCs

    G_new = { i: set() for i in range(len(SCCs)) }
    InD   = { i: 0     for i in range(len(SCCs)) }

    for (u, v) in E: # u -> v
      scc_u, scc_v = v_SCC[u], v_SCC[v]
      if scc_u != scc_v and scc_v not in G_new[ scc_u ]:
        InD[ scc_v ] += 1
        G_new[ scc_u ].add( scc_v )

    # Perform topological sort on SCCs

    scc_pred = {}
    scc_schedule = []

    Q = list( [ i for i in range(len(SCCs)) if not InD[i] ] )
    for x in Q:
      scc_pred[ x ] = None

    list_version_of_SCCs = [ list(x) for x in SCCs ]
    while Q:
      # random.shuffle(Q)

      # Prioritize update blocks instead of method
      # TODO make it O(logn) by balanced BST if needed ...
      found = False
      for i in range(len(Q)):
        m = Q[i]
        if m not in method_guard_mapping or m not in guard_method_mapping:
          u = Q.pop(i)
          found = True
          break

      if found:
        scc_schedule.append( u )

      for v in G_new[u]:
        InD[v] -= 1
        if not InD[v]:
          Q.append( v )
          scc_pred[ v ] = u

    assert len(scc_schedule) == len(SCCs), "{} != {}".format(len(scc_schedule), len(SCCs))

    #---------------------------------------------------------------------
    # Now we generate super blocks for each SCC and produce final schedule
    #---------------------------------------------------------------------

    constraint_objs = top._dag.constraint_objs

    update_schedule = []

    scc_id = 0
    for i in scc_schedule:
      scc = SCCs[i]
      if len(scc) == 1:
        u = list(scc)[0]
        update_schedule.append( u )
      else:

        # For each non-trivial SCC, we need to figure out a intra-SCC
        # linear schedule that minimizes the time to re-execute this SCC
        # due to value changes. A bad schedule may inefficiently execute
        # the SCC for many times, each of which changes a few signals.
        # The current algorithm iteratively finds the "entry block" of
        # the SCC and expand its adjancent blocks. The implementation is
        # to first find the actual entry point, and then BFS to expand the
        # footprint until all nodes are visited.

        tmp_schedule = []
        Q = deque()

        if scc_pred[i] is None:
          # We start bfs from the block that has the least number of input
          # edges in the SCC
          InD = { v: 0 for v in scc }
          for (u, v) in E: # u -> v
            if u in scc and v in scc:
              InD[ v ] += 1
          Q.append( max(InD, key=InD.get) )

        else:
          # We start bfs with the blocks that are successors of the
          # predecessor scc in the previous SCC-level topological sort.
          pred = set( SCCs[ scc_pred[i] ] )
          # Sort by names for a fixed outcome
          for x in sorted( scc, key = lambda x: x.__name__ ):
            for v in G_T[x]: # find reversed edges point back to pred SCC
              if v in pred:
                Q.append( x )

        # Perform bfs to find a heuristic schedule
        visited = set(Q)
        while Q:
          u = Q.popleft()
          tmp_schedule.append( u )
          for v in G[u]:
            if v in scc and v not in visited:
              Q.append( v )
              visited.add( v )

        scc_id += 1
        variables = set()
        for (u, v) in E:
          # Collect all variables that triggers other blocks in the SCC
          if u in scc and v in scc:
            variables.update( constraint_objs[ (u, v) ] )

        # generate a loop for scc
        # Shunning: we just simply loop over the whole SCC block
        # TODO performance optimizations using Mamba techniques within a SCC block

        def gen_wrapped_SCCblk( s, scc, src ):
          from pymtl3.dsl.errors import UpblkCyclicError

          namespace = {}
          namespace.update( locals() )
          # print src
          exec(py.code.Source( src ).compile(), namespace)

          return namespace['generated_block']

        # FIXME when there is nothing in {2} ..
        template = """
          from copy import deepcopy
          def wrapped_SCC_{0}():
            num_iters = 0
            while True:
              num_iters += 1
              {1}
              for blk in scc: # TODO Mamba
                blk()
              if {2}:
                break
              if num_iters > 100:
                raise UpblkCyclicError("Combinational loop detected at runtime in {{{3}}}!")
            # print "SCC block{0} is executed", num_iters, "times"
          generated_block = wrapped_SCC_{0}
        """

        copy_srcs  = []
        check_srcs = []
        # print_srcs = []

        for j, var in enumerate(variables):
          if issubclass( var._dsl.Type, Bits ):
            copy_srcs.append( "t{} = {}.value".format( j, var ) )
          elif is_bitstruct_class( var._dsl.Type ):
            copy_srcs.append( "t{} = {}.clone()".format( j, var ) )
          else:
            copy_srcs.append( "t{} = deepcopy({})".format( j, var ) )

          check_srcs.append( "{} == t{}".format( var, j ) )
          # print_srcs.append( "print '{}', {}, _____tmp_{}".format( var, var, j ) )

        scc_block_src = template.format( scc_id,
                                         "; ".join( copy_srcs ),
                                         " and ".join( check_srcs ),
                                         ", ".join( [ x.__name__ for x in scc] ) )
                                         # "; ".join( print_srcs ) )

        update_schedule.append( gen_wrapped_SCCblk( top, tmp_schedule, scc_block_src ) )

    # Shunning: we call line trace related pass here.
    CLLineTracePass()( top )
    CollectSignalPass()( top )
    VcdGenerationPass()( top )
    PrintWavePass()( top )

    # Shunning: we reuse ff and posedge schedules from SimpleSchedulePass
    simple = SimpleSchedulePass()
    simple.schedule_ff( top )
    simple.schedule_posedge_flip( top )

    # Currently the tick order is:
    # [ clear_cl_trace, update, ff, tracing, posedge ]
    # in order to avoid ticking for the first cycle.

    schedule = []

    # clear cl method flag
    schedule.append( top._tracing.clear_cl_trace )

    # execute all update blocks
    schedule.extend( update_schedule )

    # print trace after all update blocks
    def print_line_trace():
      print(top.num_cycles_executed, top.__class__.__name__.ljust(15), ':', top.line_trace())

    if self.line_trace_on:
      schedule.append( print_line_trace )

    # call ff blocks first
    schedule.extend( top._sched.schedule_ff )

    # append tracing related work

    if hasattr( top, "_tracing" ):
      if hasattr( top._tracing, "vcd_func" ):
        schedule.append( top._tracing.vcd_func )
      if hasattr( top._tracing, "collect_text_sigs" ):
        schedule.append( top._tracing.collect_text_sigs )

    # posedge flip
    schedule.extend( top._sched.schedule_posedge_flip )

    top._sched.new_schedule_index  = 0
    top._sched.orig_schedule_index = 0


    # Here we are trying to avoid scanning the original schedule that
    # contains methods because we will need isinstance in that case.
    # As a result we created a preprocessed list for execution and use
    # the dictionary to look up the new index of functions.

    schedule_no_method = [ x for x in schedule if not isinstance(x, CalleePort) ]
    mapping = { x : i for i, x in enumerate( schedule_no_method ) }

    def wrap_method( top, method,
                     my_idx_new, schedule_no_method,
                     my_idx_orig ):

      def actual_method( *args, **kwargs ):
        i = top._sched.new_schedule_index
        j = top._sched.orig_schedule_index

        if j > my_idx_orig:
          # This means we need to advance the current cycle to the end
          # and then normally execute until we get to the same point.
          # We use original schedule index to handle the case where
          # there are two consecutive methods.
          while i < len(schedule_no_method):
            schedule_no_method[i]()
            i += 1
          i = j = 0
          top.num_cycles_executed += 1

        # We advance from the current point i to the method's position in
        # the schedule without method just to execute those blocks
        while i < my_idx_new:
          schedule_no_method[i]()
          i += 1
        j = my_idx_orig + 1

        # Execute the method
        ret = method( *args, **kwargs )

        top._sched.new_schedule_index = i
        top._sched.orig_schedule_index = j
        return ret

      return actual_method

    for i, x in enumerate( schedule ):
      if isinstance( x, CalleePort ):
        x.original_method = x.method

        # This is to find the next non-method block's position in the
        # original schedule
        next_func   = i + 1
        while next_func < len(schedule):
          if not isinstance( schedule[next_func], CalleePort ):
            break
          next_func += 1

        # Get the index of the block in the schedule without method
        # This always exists because we append a line trace at the end
        map_next_func = mapping[ schedule[next_func] ]

        x.method = wrap_method( top, x.method,
                                map_next_func,
                                schedule_no_method,
                                i )
    top.num_cycles_executed = 0

    # This is for reset to work correctly
    top.tick = SimpleTickPass.gen_tick_function( schedule_no_method )
