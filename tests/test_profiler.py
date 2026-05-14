import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulens.feature_flags import feature_flag
from modulens.profiler import ModulensProfiler


class DefinedFunctionsTests(unittest.TestCase):
    def test_imported_callables_are_not_listed_as_defined_functions(self):
        profiler = ModulensProfiler()
        mod = types.ModuleType("example_app.helpers")
        mod.__file__ = __file__

        def checkout_config():
            return True

        checkout_config.__module__ = mod.__name__
        mod.checkout_config = checkout_config
        mod.feature_flag = feature_flag

        sys.modules[mod.__name__] = mod
        try:
            profiler.observed_modules.add(mod.__name__)
            defined = profiler._get_defined_functions()
            self.assertIn("example_app.helpers.checkout_config", defined)
            self.assertNotIn("example_app.helpers.feature_flag", defined)
        finally:
            sys.modules.pop(mod.__name__, None)


if __name__ == "__main__":
    unittest.main()
