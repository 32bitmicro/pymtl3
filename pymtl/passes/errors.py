
class SignalTypeError( Exception ):
  """ Raise when a declared signal is of wrong type """

class PassOrderError( Exception ):
  """ Raise when applying a pass to a component and some required variable
      generated by other passes is missing """
  def __init__( self, var ):
    return super( PassOrderError, self ).__init__( \
    "Please first apply other passes to generate model.{}".format( var ) )

class ModelTypeError( Exception ):
  """ Raise when a pass cannot be applied to some component type """

class MultiWriterError( Exception ):
  """ Raise when a variable is written by multiple update blocks/nets """

class NoWriterError( Exception ):
  """ Raise when a net has no writer (driver) """

class VarNotDeclaredError( Exception ):
  """ Raise when a variable in an update block is not declared """