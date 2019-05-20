#=========================================================================
# OCNPlacePass.py
#=========================================================================
# Generate placement geometric information for OCN generator.
#
# Author : Cheng Tan
# Date   : May 9, 2019

from pymtl.passes import BasePass
from collections  import deque
from graphviz     import Digraph
from errors       import PassOrderError
from BasePass     import BasePass

class OCNPlacePass( BasePass ):

  def __call__( self, top ):
    if not hasattr( top, "elaborate_physical" ):
      print( "Note that there is no elaborate_physical defined in "
             "network module:{}".format(top.__class__.__name__) )
      return

    all_components = sorted( top.get_all_components(), key=repr )
    all_components.reverse()
    for c in all_components:
      if hasattr( c, "elaborate_physical" ):
        c.elaborate_physical()
    top.elaborate_physical()

    # Generate the floorplanning script

    print '\n---- placement geometric information ----'
    print "createFence Ring4 {} {} {} {}\n".format( 
            top.dim.x, top.dim.y, top.dim.x + top.dim.w, top.dim.y + top.dim.h)
    for i, r in enumerate( top.routers ):
      print "createFence router__{} {} {} {} {}".format(
        str(i), r.dim.x, r.dim.y, r.dim.x + r.dim.w, r.dim.y + r.dim.h )

    print '---------------------'
