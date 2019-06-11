#=========================================================================
# RTLIRType.py
#=========================================================================
# Author : Peitian Pan
# Date   : March 31, 2019
"""RTLIR instance types and generation methods.

This file contains the definitions of RTLIR instance types and methods
that generate RTLIR instances. Each instance of the non-abstract class
listed in this module is a type instance or simply a type in the RTLIR
type system. Signal types is parameterized by data types defined in the
RTLIR data type module.
"""
from __future__ import absolute_import, division, print_function

import copy
import inspect
from functools import reduce

import pymtl3.dsl as dsl
from pymtl3.datatypes import Bits

from ..errors import RTLIRConversionError
from ..util.utility import collect_objs
from . import RTLIRDataType as rdt


class BaseRTLIRType( object ):
  """Base abstract class for all RTLIR instance types."""
  def __ne__( s, other ):
    return not s.__eq__( other )

class NoneType( BaseRTLIRType ):
  """Type for not yet typed RTLIR temporary variables."""
  def __eq__( s, other ):
    return isinstance( other, NoneType )

  def __hash__( s ):
    return hash(type(s))

  def __str__( s ):
    return 'NoneType'

  def __repr__( s ):
    return 'NoneType'

class Array( BaseRTLIRType ):
  """Unpacked RTLIR array type."""
  def __init__( s, dim_sizes, sub_type, unpacked = False ):
    assert isinstance( sub_type, BaseRTLIRType ), \
      "array subtype {} is not RTLIR type!".format( sub_type )
    assert not isinstance( sub_type, Array ), \
      "array subtype {} should not be array RTLIR type!".format( sub_type )
    assert len( dim_sizes ) >= 1, "array should be non-empty!"
    assert reduce( lambda s, i: s+i, dim_sizes, 0 ) > 0, \
      "array should have at least one element!"
    s.dim_sizes = dim_sizes
    s.sub_type = sub_type
    s.unpacked = unpacked

  def _is_unpacked( s ):
    return s.unpacked

  def __eq__( s, other ):
    if not isinstance( other, Array ): return False
    if s.dim_sizes != other.dim_sizes: return False
    return s.sub_type == other.sub_type

  def __hash__( s ):
    return hash((type(s), tuple(s.dim_sizes), s.sub_type))

  def get_next_dim_type( s ):
    if len( s.dim_sizes ) == 1: return copy.copy( s.sub_type )
    _s = copy.copy( s )
    _s.dim_sizes = s.dim_sizes[1:]
    return _s

  def get_dim_sizes( s ):
    return s.dim_sizes

  def get_sub_type( s ):
    return s.sub_type

  def __call__( s, obj ):
    """Return if obj be cast into type `s`."""
    return s == obj

  def __str__( s ):
    return 'Array'

  def __repr__( s ):
    return 'Array{} of {}'.format( s.dim_sizes, s.sub_type )

class Signal( BaseRTLIRType ):
  """Signal abstract RTLIR instance type.

  A Signal can be a Port, a Wire, or a Const.
  """
  def __init__( s, dtype, unpacked = False ):
    assert isinstance( dtype, rdt.BaseRTLIRDataType ), \
      "signal parameterized by non-RTLIR data type {}!".format( dtype )
    s.dtype = dtype
    s.unpacked = unpacked

  def __hash__( s ):
    return hash((type(s), s.dtype))

  def is_packed_indexable( s ):
    return isinstance( s.dtype, rdt.PackedArray )

  def get_dtype( s ):
    return s.dtype

  def _is_unpacked( s ):
    return s.unpacked

class Port( Signal ):
  """Port RTLIR instance type."""
  def __init__( s, direction, dtype, unpacked = False ):
    super( Port, s ).__init__( dtype, unpacked )
    s.direction = direction

  def __eq__( s, other ):
    return isinstance(other, Port) and s.dtype == other.dtype and \
           s.direction == other.direction

  def __hash__( s ):
    return hash((type(s), s.dtype, s.direction))

  def __str__( s ):
    return 'Port'

  def __repr__( s ):
    return 'Port of {}'.format( s.dtype )

  def get_direction( s ):
    return s.direction

  def get_next_dim_type( s ):
    assert s.is_packed_indexable(), "cannot index on unindexable port!"
    return Port( s.direction, s.dtype.get_next_dim_type(), s.unpacked )

class Wire( Signal ):
  """Wire RTLIR instance type."""
  def __init__( s, dtype, unpacked = False ):
    super( Wire, s ).__init__( dtype, unpacked )

  def __eq__( s, other ):
    return isinstance(other, Wire) and s.dtype == other.dtype

  def __hash__( s ):
    return hash((type(s), s.dtype))

  def __str__( s ):
    return 'Wire'

  def __repr__( s ):
    return 'Wire of {}'.format( s.dtype )

  def get_next_dim_type( s ):
    assert s.is_packed_indexable(), "cannot index on unindexable wire!"
    return Wire( s.dtype.get_next_dim_type(), s.unpacked )

class Const( Signal ):
  """Const RTLIR instance type."""
  def __init__( s, dtype, unpacked = False ):
    super( Const, s ).__init__( dtype, unpacked )

  def __eq__( s, other ):
    return isinstance(other, Const) and s.dtype == other.dtype

  def __hash__( s ):
    return hash((type(s), s.dtype))

  def __str__( s ):
    return 'Const'

  def __repr__( s ):
    return 'Const of {}'.format( s.dtype )

  def get_next_dim_type( s ):
    assert s.is_packed_indexable(), "cannot index on unindexable constant!"
    return Const( s.dtype.get_next_dim_type(), s.unpacked )

class InterfaceView( BaseRTLIRType ):
  """RTLIR instance type for a view of an interface."""
  def __init__( s, name, properties, obj = None, unpacked = False ):
    s.name = name
    s.properties = properties
    s.obj = obj
    s.cls = obj.__class__
    s.unpacked = unpacked

    if obj is not None:
      try:
        s.args = obj._dsl.args
        s.kwargs = obj._dsl.kwargs
      except AttributeError:
        assert False, "interface object {} is not constructed!".format( s.obj )

    # Sanity check
    for name, rtype in properties.iteritems():
      assert isinstance(name, str) and _is_of_type(rtype, (Port, InterfaceView)), \
        "invalid attribute {} of interface {}: only ports and interfaces allowed!". \
          format( name, s.name )

  def __str__( s ):
    return 'InterfaceView ' + s.name

  def __repr__( s ):
    return 'InterfaceView {}'.format( s.name )

  def _is_unpacked( s ):
    return s.unpacked

  def __eq__( s, other ):
    return isinstance(other, InterfaceView) and s.name == other.name

  def __hash__( s ):
    return hash((type(s), s.name))

  def get_name( s ):
    return s.name

  def get_class( s ):
    return s.cls

  def get_args( s ):
    if s.obj is not None:
      return ( s.args, s.kwargs )
    else:
      return ( [], {} )

  def get_input_ports( s ):
    return sorted(filter(
      lambda id__port: id__port[1].direction == 'input',
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def get_output_ports( s ):
    return sorted(filter(
      lambda id__port1: id__port1[1].direction == 'output',
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def has_property( s, p ):
    return p in s.properties

  def get_property( s, p ):
    return s.properties[ p ]

  def get_all_ports( s ):
    return sorted(filter(
      lambda name_port: isinstance( name_port[1], Port ),
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def get_all_ports_packed( s ):
    return sorted(filter(
      lambda id__t2: \
        ( isinstance( id__t2[1], Port ) and not id__t2[1]._is_unpacked() ) or \
        ( isinstance( id__t2[1], Array ) and isinstance( id__t2[1].get_sub_type(), Port ) \
          and not id__t2[1]._is_unpacked() ),
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def get_all_properties( s ):
    return sorted( s.properties.iteritems(), lambda kv: kv[0] )

  def get_all_properties_packed( s ):
    return sorted( filter( lambda x: not x[1]._is_unpacked(), s.properties.iteritems() ),
        key = lambda kv: kv[0] )

class Component( BaseRTLIRType ):
  """RTLIR instance type for a component."""
  def __init__( s, obj, properties, unpacked = False ):
    s.name = obj.__class__.__name__
    s.params = s._gen_parameters( obj )
    s.properties = properties
    s.unpacked = unpacked

  def _gen_parameters( s, obj ):
    # s.argspec: static code reflection results
    # _dsl.args: all unnamed arguments supplied to construct()
    # _dsl.kwargs: all named arguments supplied to construct()
    try:
      argspec = inspect.getfullargspec( getattr( obj, 'construct' ) )
      assert not argspec.varkw, "keyword args are not allowed for construct!"
      assert not argspec.kwonlyargs, "keyword args are not allowed for construct!"
    except AttributeError:
      argspec = inspect.getargspec( getattr( obj, 'construct' ) )
      assert not argspec.keywords, "keyword args are not allowed for construct!"
    assert not argspec.varargs, "varargs are not allowed for construct!"
    arg_names = argspec.args[1:]

    defaults = argspec.defaults or ()
    num_args = len(arg_names)
    num_supplied = len(obj._dsl.args) + len(obj._dsl.kwargs)
    num_defaults = len(defaults)

    # No default values: each arg is either keyword or unnamed
    # Has default values: num. supplied values + num. of defaults >= num. args
    assert num_args == num_supplied or num_args <= num_supplied + num_defaults
    use_defaults = num_args != num_supplied

    ret = []
    # Handle method construct arguments
    for idx, arg_name in enumerate(arg_names):

      # Use values from _dsl.args
      if idx < len(obj._dsl.args):
        ret.append((arg_name, obj._dsl.args[idx]))

      # Use values from _dsl.kwargs
      elif arg_name in obj._dsl.kwargs:
        ret.append((arg_name, obj._dsl.kwargs[arg_name]))

      # Use default values
      else:
        assert use_defaults
        ret.append((arg_name, defaults[idx-len(arg_names)]))

    return ret

  def _is_unpacked( s ):
    return s.unpacked

  def __eq__( s, other ):
    return isinstance(other, Component) and s.name == other.name and \
           s.params == other.params

  def __hash__( s ):
    return hash((type(s), s.name, tuple(s.params)))

  def __str__( s ):
    return 'Component'

  def __repr__( s ):
    return 'Component {}'.format( s.name )

  def get_name( s ):
    return s.name

  def get_params( s ):
    return s.params

  def get_ports( s ):
    return sorted(filter(
      lambda id__port3: isinstance( id__port3[1], Port ),
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def get_ports_packed( s ):
    return sorted(filter(
      lambda id__t4: \
        ( isinstance( id__t4[1], Port ) and not id__t4[1]._is_unpacked() ) or \
        ( isinstance( id__t4[1], Array ) and isinstance( id__t4[1].get_sub_type(), Port ) \
          and not id__t4[1]._is_unpacked() ),
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def get_wires( s ):
    return sorted(filter(
      lambda id__wire: isinstance( id__wire[1], Wire ),
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def get_wires_packed( s ):
    return sorted(filter(
      lambda id__t5: \
        ( isinstance( id__t5[1], Wire ) and not id__t5[1]._is_unpacked() ) or \
        ( isinstance( id__t5[1], Array ) and isinstance( id__t5[1].get_sub_type(), Wire ) \
          and not id__t5[1]._is_unpacked() ),
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def get_consts( s ):
    return sorted(filter(
      lambda id__const: isinstance( id__const[1], Const ),
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def get_consts_packed( s ):
    return sorted(filter(
      lambda id__t6: \
        ( isinstance( id__t6[1], Const ) and not id__t6[1]._is_unpacked() ) or \
        ( isinstance( id__t6[1], Array ) and isinstance( id__t6[1].get_sub_type(), Const ) \
          and not id__t6[1]._is_unpacked() ),
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def get_ifc_views( s ):
    return sorted(filter(
      lambda id__ifc: isinstance( id__ifc[1], InterfaceView ),
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def get_ifc_views_packed( s ):
    return sorted(filter(
      lambda id__t7: \
        ( isinstance( id__t7[1], InterfaceView ) and not id__t7[1]._is_unpacked() ) or \
        ( isinstance( id__t7[1], Array ) and isinstance( id__t7[1].get_sub_type(),InterfaceView ) \
          and not id__t7[1]._is_unpacked() ),
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def get_subcomps( s ):
    return sorted(filter(
      lambda id__subcomp: isinstance( id__subcomp[1], Component ),
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def get_subcomps_packed( s ):
    return sorted(filter(
      lambda id__t9: \
        ( isinstance( id__t9[1], Component ) and not id__t9[1]._is_unpacked() ) or \
        ( isinstance( id__t9[1], Array ) and isinstance( id__t9[1].get_sub_type(), Component ) \
          and not id__t9[1]._is_unpacked() ),
      s.properties.iteritems()
    ), key = lambda kv: kv[0])

  def has_property( s, p ):
    return p in s.properties

  def get_property( s, p ):
    return s.properties[ p ]

  def get_all_properties( s ):
    return s.properties

#-------------------------------------------------------------------------
# Internal Methods
#-------------------------------------------------------------------------

def _is_rtlir_ifc_convertible( obj ):
  valid_ifc_attributes = ( dsl.InPort, dsl.OutPort, dsl.Interface )
  if isinstance( obj, list ):
    while isinstance( obj, list ):
      assert len( obj ) > 0, "one dimension of {} is 0!".format( obj )
      obj = obj[0]
    return _is_rtlir_ifc_convertible( obj )
  elif isinstance( obj, valid_ifc_attributes ):
    return True
  else:
    return False

def _unpack( id_, Type ):
  if not isinstance( Type, Array ): return [ ( id_, Type ) ]
  ret = []
  for idx in range( Type.get_dim_sizes()[0] ):
    ret.append( ( id_+'[{}]'.format(idx), Type.get_next_dim_type() ) )
    ret.extend(_unpack(id_+'[{}]'.format( idx ), Type.get_next_dim_type()))
  return ret

def _add_packed_instances( id_, Type, properties ):
  assert isinstance( Type, Array ), "{} is not an array type!".format( Type )
  for _id, _Type in _unpack( id_, Type ):
    assert hasattr( _Type, 'unpacked' ), \
      "{} {} is not unpacked!".format( _Type, _id )
    _Type.unpacked = True
    properties[ _id ] = _Type

def _handle_Array( obj ):
  assert len( obj ) > 0, "list {} is empty!".format( obj )
  ref_type = get_rtlir( obj[0] )
  assert \
    reduce( lambda res,i: res and (get_rtlir(i)==ref_type), obj, True ), \
    'all elements of array {} must have the same type {}!'.format(
      obj, ref_type )
  dim_sizes = []
  while isinstance( obj, list ):
    assert len( obj ) > 0, "{} is an empty list!".format( obj )
    dim_sizes.append( len( obj ) )
    obj = obj[0]
  return Array( dim_sizes, get_rtlir( obj ) )

def _handle_InPort( obj ):
  return Port( 'input', rdt.get_rtlir_dtype( obj ) )

def _handle_OutPort( obj ):
  return Port( 'output', rdt.get_rtlir_dtype( obj ) )

def _handle_Wire( obj ):
  return Wire( rdt.get_rtlir_dtype( obj ) )

def _handle_Const( obj ):
  return Const( rdt.get_rtlir_dtype( obj ) )

def _handle_Interface( obj ):
  properties = {}
  collected_objs = collect_objs( obj, object, True )
  for _id, _obj in collected_objs:
    # TODO: warn the user about a silently dropped attribute?
    # assert False, \
      # "non-port-or-interface {} in interface {}!".format( _obj, obj )
    if _is_rtlir_ifc_convertible( _obj ):
      _obj_type = get_rtlir( _obj )
      properties[ _id ] = _obj_type
      if isinstance( _obj_type, Array ):
        _add_packed_instances( _id, _obj_type, properties )
  return InterfaceView( obj.__class__.__name__, properties, obj )

def _handle_Component( obj ):
  properties = {}
  collected_objs = collect_objs( obj, object, True )
  for _id, _obj in collected_objs:
    # Untranslatable attributes will be ignored
    # TODO: warn the user about a silently dropped attribute?
    if is_rtlir_convertible( _obj ):
      _obj_type = get_rtlir( _obj )
      properties[ _id ] = _obj_type
      if isinstance( _obj_type, Array ):
        _add_packed_instances( _id, _obj_type, properties )
  return Component( obj, properties )

def _is_of_type( obj, Type ):
  """Return True is `obj` is of RTLIR type `Type`."""
  if isinstance( obj, Type ):
    return True
  if isinstance( obj, Array ) and isinstance( obj.get_sub_type(), Type ):
    return True
  return False

_RTLIR_ifc_handlers = [
  ( list,          _handle_Array ),
  ( dsl.InPort,    _handle_InPort ),
  ( dsl.OutPort,   _handle_OutPort ),
  ( dsl.Interface, _handle_Interface ),
]

_RTLIR_handlers = [
  ( list,          _handle_Array ),
  ( dsl.InPort,    _handle_InPort ),
  ( dsl.OutPort,   _handle_OutPort ),
  ( dsl.Wire,      _handle_Wire ),
  ( ( int, Bits ), _handle_Const ),
  ( dsl.Interface, _handle_Interface ),
  ( dsl.Component, _handle_Component ),
]

#-------------------------------------------------------------------------
# Public APIs
#-------------------------------------------------------------------------

def get_component_ifc_rtlir( obj ):
  """Return the RTLIR of the interfaces of component `obj`."""
  primitive_types = tuple( x[0] for x in _RTLIR_ifc_handlers[1:] )

  def _is_interface( obj ):
    _type = type(obj)
    if isinstance( obj, primitive_types ):
      return True
    if not isinstance( obj, list ):
      return False
    while isinstance( obj, list ):
      assert len( obj ) > 0, "{} is an empty list!".format( obj )
      obj = obj[0]
    return isinstance( obj, primitive_types )

  def _get_ifc_rtlir( obj ):
    for Type, handler in _RTLIR_ifc_handlers:
      if isinstance( obj, Type ):
        return handler( obj )
    return None

  try:
    assert isinstance(obj, dsl.Component), \
      "the given object is not a PyMTL component!"
    properties = {}
    collected_objs = collect_objs( obj, object, True )
    for _id, _obj in collected_objs:
      if _is_interface( _obj ):
        _obj_type = _get_ifc_rtlir( _obj )
        if _obj_type is not None:
          properties[ _id ] = _obj_type
          if isinstance( _obj_type, Array ):
            _add_packed_instances( _id, _obj_type, properties )
    return Component( obj, properties )
  except AssertionError as e:
    msg = '' if e.args[0] is None else e.args[0]
    raise RTLIRConversionError( obj, msg )

def is_rtlir_convertible( obj ):
  """Return if `obj` can be converted into an RTLIR instance."""
  pymtl_constructs = (
    dsl.InPort, dsl.OutPort, dsl.Wire,
    Bits, dsl.Interface, dsl.Component,
  )
  # TODO: improve this long list of isinstance check
  if isinstance( obj, list ):
    while isinstance( obj, list ):
      assert len( obj ) > 0
      obj = obj[0]
    return is_rtlir_convertible( obj )
  elif isinstance( obj, pymtl_constructs ):
    return True
  elif isinstance( obj, int ):
    return True
  else:
    return False

def get_rtlir( obj ):
  """Return an RTLIR instance corresponding to `obj`."""
  try:
    for Type, handler in _RTLIR_handlers:
      if isinstance( obj, Type ):
        return handler( obj )
    # Cannot convert `obj` into RTLIR representation
    assert False, 'unrecognized object {}!'.format( obj )
  except AssertionError as e:
    msg = '' if e.args[0] is None else e.args[0]
    raise RTLIRConversionError( obj, msg )