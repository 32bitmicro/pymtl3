"""Expose method that returns RTLIR.

This module exposes get_rtlir method that converts PyMTL components
to RTLIR representation.
"""
from __future__ import absolute_import, division, print_function

from .behavioral import (
    BehavioralRTLIR,
    BehavioralRTLIRGenPass,
    BehavioralRTLIRTypeCheckPass,
    BehavioralRTLIRVisualizationPass,
)
from .rtype import RTLIRDataType, RTLIRType
from .rtype.RTLIRDataType import get_rtlir_dtype
from .rtype.RTLIRType import get_rtlir, is_rtlir_convertible
from .structural import StructuralRTLIRGenPass, StructuralRTLIRSignalExpr
