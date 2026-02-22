# confy/exceptions.py
"""
confy.exceptions
----------------

Custom exceptions for confy.
"""


class MissingMandatoryConfig(Exception):
    """
    Raised when one or more mandatory config keys are missing.
    """

    def __init__(self, keys):
        super().__init__(f"Missing mandatory configuration keys: {', '.join(keys)}")
        self.missing_keys = keys
