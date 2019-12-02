"""
=========================================================================
test_stateful
=========================================================================
Hypothesis stateful testing on RTL and CL model

Author : Yixiao Zhang
  Date : May 22, 2019
"""

from copy import deepcopy

import hypothesis.strategies as st
from hypothesis import PrintSettings
from hypothesis import reproduce_failure as rf
from hypothesis import settings
from hypothesis.searchstrategy import SearchStrategy
from hypothesis.stateful import *

from pymtl3 import *
from pymtl3.passes import GenDAGPass, OpenLoopCLPass

from .test_wrapper import *


#-------------------------------------------------------------------------
# bitstype_strategy
#-------------------------------------------------------------------------
def bitstype_strategy( bits ):
  return st.integers( min_value=0, max_value=( 1 << bits.nbits ) - 1 )


#-------------------------------------------------------------------------
# bits_struct_strategy
#-------------------------------------------------------------------------
def bits_struct_strategy( bits_struct_type,
                          predefined={},
                          remaining_names=None ):

  field_strategies = {}
  for name, field_type in bits_struct_type.fields:
    predefined_field = predefined.get( name, {} )
    field_strategies[ name ] = get_strategy_from_type(
        field_type, predefined_field, remaining_names )

  @st.composite
  def strategy( draw ):
    new_bits_struct = bits_struct_type()
    for name, field_type in bits_struct_type.fields:
      # recursively draw st
      data = draw( field_strategies[ name ] )
      setattr( new_bits_struct, name, data )
    return new_bits_struct

  return strategy()


#-------------------------------------------------------------------------
# get_strategy_from_type
#-------------------------------------------------------------------------
def get_strategy_from_type( dtype, predefined={}, remaining_names=None ):
  if isinstance( predefined, tuple ):
    assert isinstance( predefined[ 0 ], SearchStrategy )
    remaining_names.discard( predefined[ 1 ] )
    return predefined[ 0 ]

  if isinstance( dtype(), Bits ):
    if predefined:
      raise TypeError( "Need strategy for Bits type {}".format(
          repr( dtype ) ) )
    return bitstype_strategy( dtype() )

  if isinstance( dtype(), BitStruct ):
    return bits_struct_strategy( dtype, predefined, remaining_names )

  raise TypeError( "Argument strategy for {} not supported".format( dtype ) )


#-------------------------------------------------------------------------
# BaseStateMachine
#-------------------------------------------------------------------------
class BaseStateMachine( RuleBasedStateMachine ):

  def __init__( s ):
    super( BaseStateMachine, s ).__init__()

    s.dut = deepcopy( s.preconstruct_dut )
    s.ref = deepcopy( s.preconstruct_ref )

    def wrap_line_trace( top ):

      def new_str( self ):
        if self.method.called and self.rdy.called and self.rdy.saved_ret:
          kwargs_str = kwarg_to_str( self.method.saved_kwargs )
          ret_str = ( "" if self.method.saved_ret is None else
                      " -> " + str( self.method.saved_ret ) )
          return "{name}({kwargs}){ret}  ".format(
              name=self._dsl.my_name, kwargs=kwargs_str, ret=ret_str )
        elif self.rdy.called:
          if self.rdy.saved_ret:
            return "-  "
          else:
            return "#  "
        elif not self.rdy.called:
          return ".  "
        return "X  "

      func = top.line_trace

      def line_trace():
        trace = func() + "  "
        for ifc in top.top_level_nb_ifcs:
          trace += new_str( ifc )
        return trace

      top.line_trace = line_trace

    wrap_line_trace( s.dut )

    # elaborate dut
    s.dut.elaborate()
    s.dut.apply( GenDAGPass() )
    s.dut.apply( OpenLoopCLPass() )
    s.dut.lock_in_simulation()

    # elaborate ref
    s.ref.elaborate()
    s.ref.apply( GenDAGPass() )
    s.ref.apply( OpenLoopCLPass() )
    s.ref.lock_in_simulation()
    s.ref.hide_line_trace = True


#-------------------------------------------------------------------------
# TestStateful
#-------------------------------------------------------------------------
class TestStateful( BaseStateMachine ):

  def error_line_trace( self, error_msg="" ):
    print( "============================= error ========================" )
    print( error_msg )
    raise ValueError( error_msg )


#-------------------------------------------------------------------------
# wrap_method
#-------------------------------------------------------------------------
def wrap_method( method_spec, arguments ):
  method_name = method_spec.method_name

  @rename( method_name + "_rdy" )
  def method_rdy( s ):
    dut_rdy = s.dut.__dict__[ method_name ].rdy()
    ref_rdy = s.ref.__dict__[ method_name ].rdy()

    if dut_rdy and not ref_rdy:
      error_msg = "Dut method is rdy but reference is not: " + method_name
      s.error_line_trace( error_msg )

    if not dut_rdy and ref_rdy:
      error_msg = "Reference method is rdy but dut is not: " + method_name
      s.error_line_trace( error_msg )
    return dut_rdy

  @precondition( lambda s: method_rdy( s ) )
  @rule(**arguments )
  @rename( method_name )
  def method_rule( s, **kwargs ):
    dut_result = s.dut.__dict__[ method_name ](**kwargs )
    ref_result = s.ref.__dict__[ method_name ](**kwargs )

    ret_type = method_spec.rets_type
    if ret_type:
      if len( ret_type.fields ) > 1:
        ref_result = method_spec.rets_type(*ref_result )
      else:
        ref_result = method_spec.rets_type( ref_result )

    #compare results
    if dut_result != ref_result:

      error_msg = """mismatch found in method {method}:
  - args: {data}
  - ref result: {ref_result}
  - dut result: {dut_result}
  """.format(
          method=method_name,
          data=kwarg_to_str( kwargs ),
          ref_result=ref_result,
          dut_result=dut_result )

      s.error_line_trace( error_msg )

  return method_rule, method_rdy


def get_strategy_from_list( st_list ):
  # Generate a nested dictionary for customized strategy
  # e.g. [ ( 'enq.msg', st1 ), ('deq.msg.msg0', st2 ) ]
  # turns into {
  #  'enq': { 'msg': st1 },
  #  'deq': { 'msg': { 'msg0': st2 } }
  # }
  all_field_st = {}
  all_subfield_st = {}

  # First go through all customized strategy,
  # Create a dict of ( field, [ ( subfield, strategy ) ] ) for non-leaf
  # Create a dict of ( field, strategy ) for leaf
  for name, strat in st_list:
    field_name, subfield_name = name.split( ".", 1 )
    field_st = all_field_st.setdefault( field_name, {} )
    # leaf
    if not "." in subfield_name:
      field_st[ subfield_name ] = strat

    # non-leaf
    else:
      subfield_list = all_subfield_st.setdefault( field_name, [] )
      subfield_list += [( subfield_name, strat ) ]

  # Recursively generate dict for subfields
  for field_name, subfield_list in all_subfield_st.items():
    subfield_dict = get_strategy_from_list( subfield_list )
    for subfield in subfield_dict.keys():
      # If a field has a customized strategy, there should not be any
      # strategy for its subfields. e.g. s.enq.msg and s.enq.msg.msg0 should
      # not be in st_list simultaneously
      field_st = all_field_st[ field_name ]
      assert not subfield in field_st.keys(), (
          "Found customized strategy for {}. "
          "Separate strategy for its fields are not allowed".format(
              field_st[ subfield ][ 1 ] ) )
    all_field_st[ field_name ].update( subfield_dict )
  return all_field_st


#-------------------------------------------------------------------------
# create_test_state_machine
#-------------------------------------------------------------------------
def create_test_state_machine( dut,
                               ref,
                               method_specs=None,
                               argument_strategy={} ):
  Test = type( dut.model_name + "_TestStateful", TestStateful.__bases__,
               dict( TestStateful.__dict__ ) )

  Test.preconstruct_dut = deepcopy( dut )
  Test.preconstruct_ref = deepcopy( ref )

  dut.elaborate()

  if not method_specs:
    try:
      method_specs = dut.method_specs
    except AttributeError:
      raise "No method specs specified"

  # Store ( strategy, full_name )
  arg_st_with_full_name = []
  all_st_full_names = set()
  for name, strat in argument_strategy:

    if not isinstance( strat, SearchStrategy ):
      raise TypeError( "Only strategy is allowed! got {} for {}".format(
          type( strat ), name ) )

    arg_st_with_full_name += [( name, ( strat, name ) ) ]
    all_st_full_names.add( name )

  # get nested dict of strategy
  method_arg_st = get_strategy_from_list( arg_st_with_full_name )

  # go through spec for each method
  for method_name, spec in method_specs.items():
    arg_st = method_arg_st.get( method_name, {} )

    # create strategy based on types and predefined customization
    for arg, dtype in spec.args:
      arg_st[ arg ] = get_strategy_from_type( dtype, arg_st.get( arg, {} ),
                                              all_st_full_names )

    # wrap method
    method_rule, method_rdy = wrap_method( method_specs[ method_name ], arg_st )
    setattr( Test, method_name, method_rule )
    setattr( Test, method_name + "_rdy", method_rdy )

  assert not all_st_full_names, "Got strategy for unrecognized field: {}".format(
      list_string( all_st_full_names ) )
  return Test


#-------------------------------------------------------------------------
# run_test_state_machine
#-------------------------------------------------------------------------
def run_test_state_machine( dut,
                            ref,
                            arg_strategy={},
                            reproduce_failure=None ):

  machine = create_test_state_machine( dut, ref, argument_strategy=arg_strategy )
  machine.TestCase.settings = settings(
    max_examples=50,
    stateful_step_count=100,
    deadline=None,
    verbosity=Verbosity.verbose,
    database=None
  )

  if reproduce_failure:
    rf(*reproduce_failure )( machine )
  run_state_machine_as_test( machine )
