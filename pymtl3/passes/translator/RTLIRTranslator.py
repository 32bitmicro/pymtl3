#=========================================================================
# RTLIRTranslator.py
#=========================================================================
# Author : Peitian Pan
# Date   : March 15, 2019
"""Provide translators that convert RTLIR to backend representation."""
from __future__ import absolute_import, division, print_function

from functools import reduce

from .BaseRTLIRTranslator import TranslatorMetadata
from .behavioral import BehavioralTranslator
from .errors import RTLIRTranslationError
from .structural import StructuralTranslator


def mk_RTLIRTranslator( _StructuralTranslator, _BehavioralTranslator ):
  """Return an RTLIRTranslator from the two given translators."""
  class _RTLIRTranslator( _StructuralTranslator, _BehavioralTranslator ):
    """Template translator class parameterized by behavioral/structural translator.

    Components are assembled here because they have both behavioral
    and structural parts. This translator also generates the overall
    code layout of the backend representation.
    """

    # Override
    def __init__( s, top ):
      super( _RTLIRTranslator, s ).__init__( top )
      s.hierarchy = TranslatorMetadata()

    # Override
    def translate( s ):

      def get_component_nspace( namespace, m ):
        ns = TranslatorMetadata()
        for name, metadata_d in vars(namespace).iteritems():
          # Hierarchical metadata will not be added
          if m in metadata_d:
            setattr( ns, name, metadata_d[m] )
        return ns

      def translate_component( m, components, translated ):
        for child in m.get_child_components():
          translate_component( child, components, translated )
        if not s.structural.component_unique_name[m] in translated:
          components.append(
            s.rtlir_tr_component(
              get_component_nspace( s.behavioral, m ),
              get_component_nspace( s.structural, m )
          ) )
          translated.append( s.structural.component_unique_name[m] )
        s.gen_hierarchy_metadata( 'decl_type_vector', 'decl_type_vector' )
        s.gen_hierarchy_metadata( 'decl_type_array', 'decl_type_array' )
        s.gen_hierarchy_metadata( 'decl_type_struct', 'decl_type_struct' )

      s.component = {}
      # Generate backend representation for each component
      s.hierarchy.components = []
      s.hierarchy.decl_type_vector = []
      s.hierarchy.decl_type_array = []
      s.hierarchy.decl_type_struct = []

      try:
        s.translate_behavioral( s.top )
        s.translate_structural( s.top )
        translate_component( s.top, s.hierarchy.components, [] )
      except AssertionError as e:
        msg = '' if e.args[0] is None else e.args[0]
        raise RTLIRTranslationError( s.top, msg )

      # Generate the representation for all components
      s.hierarchy.component_src = s.rtlir_tr_components(s.hierarchy.components)

      # Generate the final backend code layout
      s.hierarchy.src = s.rtlir_tr_src_layout( s.hierarchy )

    def gen_hierarchy_metadata( s, structural_ns, hierarchy_ns ):
      metadata = getattr( s.structural, structural_ns, [] )
      List = getattr( s.hierarchy, hierarchy_ns )
      for Type, data in metadata:
        if not s.in_list( Type, List ):
          List.append( ( Type, data ) )

    def in_list( s, dtype, List ):
      return reduce( lambda r, x: r or x[0] == dtype, List, False )

    #---------------------------------------------------------------------
    # Methods to be implemented by the backend translator
    #---------------------------------------------------------------------

    def rtlir_tr_src_layout( s, hierarchy ):
      raise NotImplementedError()

    def rtlir_tr_components( s, components ):
      raise NotImplementedError()

    def rtlir_tr_component( s, behavioral, structural ):
      raise NotImplementedError()

  return _RTLIRTranslator

RTLIRTranslator = mk_RTLIRTranslator( BehavioralTranslator, StructuralTranslator )
