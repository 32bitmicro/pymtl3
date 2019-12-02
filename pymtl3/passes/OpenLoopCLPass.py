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
from pymtl3.dsl import CalleeIfcCL, CalleePort

import os, py, random
from collections import deque
from graphviz import Digraph

from pymtl3.datatypes import Bits1
from pymtl3.dsl import CalleePort, CalleeIfcCL
from pymtl3.dsl.errors import UpblkCyclicError

from .BasePass import BasePass, PassMetadata
from .errors import PassOrderError
from .SimpleSchedulePass import dump_dag, make_double_buffer_func


class OpenLoopCLPass( BasePass ):
  def __call__( self, top ):
    if not hasattr( top._dag, "all_constraints" ):
      raise PassOrderError( "all_constraints" )

    top._sched = PassMetadata()

    self.schedule_with_top_level_callee( top )

  def schedule_with_top_level_callee( self, top ):

    # Construct the graph with top level callee port
    V = top._dag.final_upblks - top.get_all_update_ff()

    # We collect all top level callee ports/nonblocking callee interfaces
    top_level_callee_ports = top.get_all_object_filter(
      lambda x: isinstance(x, CalleePort) and x.get_host_component() is top )

    # Now we need to check if cl_trace has been applied. If so, we need to
    # use raw_method
    if hasattr( top, "_cl_trace" ): get_raw_method = lambda x: x.raw_method
    else:                           get_raw_method = lambda x: x.method

    top_level_nb_ifcs = top.get_all_object_filter(
      lambda x: isinstance(x, CalleeIfcCL) and x.get_host_component() is top )

    # We still tell the top level
    method_callee_mapping = {}
    method_guard_mapping  = {}

    top.top_level_nb_ifcs = []

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
      method_guard_mapping [x.method] = x.rdy
      m = get_raw_method( x.method )
      assert m not in method_callee_mapping
      method_callee_mapping[m] = x.method

    E   = top._dag.all_constraints
    G   = { v: [] for v in V }
    G_T = { v: [] for v in V }

    for (u, v) in E: # u -> v
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

      E.add( (xx, yy) )
      G  [xx].append( yy )
      G_T[yy].append( xx )

    if 'MAMBA_DAG' in os.environ:
      dump_dag( top, V, E )

    #---------------------------------------------------------------------
    # Run Kosaraju's algorithm to shrink all strongly connected components
    # (SCCs) into super nodes
    #---------------------------------------------------------------------

    # First dfs on G to generate reverse post-order (RPO)
    # Shunning: we emulate the system stack to implement non-recursive
    # post-order DFS algorithm. At the beginning, I implemented a more
    # succinct recursive DFS but it turned out that a 1500-depth chain in
    # the graph will reach the CPython max recursion depth.
    # https://docs.python.org/3/library/sys.html#sys.getrecursionlimit

    PO = []

    vertices = list(G.keys())
    random.shuffle(vertices)
    visited = set()

    # The commented algorithm loyally emulates the system stack by storing
    # the loop index in each stack element and push only one new element
    # to stack in every iteration. This is basically what recursive dfs
    # does.
    #
    # for u in vertices:
    #   if u not in visited:
    #     stack = [ (u, False) ]
    #     while stack:
    #       u, idx = stack.pop()
    #       visited.add( u )
    #       if idx == len(G[u]):
    #         PO.append( u )
    #       else:
    #         while idx < len(G[u]) and G[u][-idx] in visited:
    #           idx += 1
    #         if idx < len(G[u]):
    #           stack.append( (u, idx) )
    #           stack.append( (G[u][-idx], 0) )
    #         else:
    #           PO.append( u )

    # The following algorithm push all adjacent elements to the stack at
    # once and later check visited set to avoid redundant visit (instead
    # of checking visited set when pushing element to the stack). I added
    # a second_visit flag to add the node to post-order.

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
      random.shuffle(Q)

      # Prioritize update blocks instead of method
      # TODO make it O(logn) by balanced BST if needed ...

      u = None
      for i in range(len(Q)):
        if len(SCCs[Q[i]]) == 1:
          if list_version_of_SCCs[Q[i]][0] not in method_guard_mapping:
            u = Q.pop(i)
            break

      if u is None:
        u = Q.pop()

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

    schedule = []

    scc_id = 0
    for i in scc_schedule:
      scc = SCCs[i]
      if len(scc) == 1:
        u = list(scc)[0]

        # We add the corresponding rdy before the method

        if u in method_guard_mapping:
          schedule.append( method_guard_mapping[ u ] )
          top.top_level_nb_ifcs.append( u.get_parent_object() )

        schedule.append( u )
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
        print_srcs = []

        for j, var in enumerate(variables):
          copy_srcs .append( "_____tmp_{} = deepcopy({})".format( j, var ) )
          check_srcs.append( "{} == _____tmp_{}".format( var, j ) )
          print_srcs.append( "print '{}', {}, _____tmp_{}".format( var, var, j ) )

        scc_block_src = template.format( scc_id,
                                         "; ".join( copy_srcs ),
                                         " and ".join( check_srcs ),
                                         ", ".join( [ x.__name__ for x in scc] ) )
                                         # "; ".join( print_srcs ) )
        schedule.append( gen_wrapped_SCCblk( top, tmp_schedule, scc_block_src ) )

    # The last element is always line trace
    def print_line_trace():
      print(top.line_trace())

    schedule.append( print_line_trace )

    # Sequential blocks and double buffering
    schedule.extend( list(top._dsl.all_update_ff) )
    func = make_double_buffer_func( top )
    if func is not None:
      schedule.append( func )

    if hasattr( top, "_cl_trace" ):
      schedule.append( top._cl_trace.clear_cl_trace )

    top._sched.new_schedule_index  = 0
    top._sched.orig_schedule_index = 0

    # Here we are trying to avoid scanning the original schedule that
    # contains methods because we will need isinstance in that case.
    # As a result we created a preprocessed list for execution and use
    # the dictionary to look up the new index of functions.

    schedule_no_method = [ x for x in schedule if not isinstance(x, CalleePort) ]
    mapping = { x : i for i, x in enumerate( schedule_no_method ) }

    def wrap_method( top, method,
                     my_idx_new, next_idx_new, schedule_no_method,
                     my_idx_orig, next_idx_orig ):

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

        # Execute the method
        ret = method( *args, **kwargs )

        # Execute all update blocks before the next method. Note that if
        # there are several consecutive methods, my_idx_new is equal to next_idx_new
        while i < next_idx_new:
          schedule_no_method[i]()
          i += 1
        j = next_idx_orig

        if i == len(schedule_no_method):
          i = j = 0
          top.num_cycles_executed += 1

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

        # Get the index of the next method in the schedule without method
        next_method = i + 1
        while next_method < len(schedule):
          if isinstance( schedule[next_method], CalleePort ):
            break
          next_method += 1

        # If there is another method after me, I calculate the range of
        # blocks that I need to call and then stop before the user calls
        # the next method.
        if next_method < len(schedule):
          next_func = next_method
          while next_func < len(schedule):
            if not isinstance( schedule[next_func], CalleePort ):
              break
            next_func += 1
          # Get the index in the compacted schedule
          map_next_func_of_next_method = mapping[ schedule[next_func] ]
        else:
          map_next_func_of_next_method = len(schedule_no_method)

        x.method = wrap_method( top, x.method,
                                map_next_func, map_next_func_of_next_method,
                                schedule_no_method,
                                i, next_method )
    top.num_cycles_executed = 0

    def normal_tick():
      for blk in schedule_no_method:
        blk()
    top.tick = normal_tick

    return schedule
