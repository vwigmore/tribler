class ConfigObjConverter(object):
    """
    This class contains code to migrate the old configuration system we used to ConfigObj.
    """
    def __init__(self, session):
        self.session = session

    def convert(self):
        """
        Calling this method will convert all configuration files to the newer ConfigObj format.
        """
        self.convert_session_config()

    def convert_session_config(self):
        """
        Convert the .conf file to ConfigObj format
        """
