# SPDX-License-Identifier: Apache-2.0
"""avocado-zram-compressor.bbclass: which kernels need a compressor module.

Runs the class's own avocado_zram_compressor_module() against the relevant
lines of real Jetson kernel configs.

Run with:
    PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests
"""

import re
import unittest
from pathlib import Path

CLASS = Path(__file__).resolve().parent.parent / "classes" / "avocado-zram-compressor.bbclass"


def _load():
    src = CLASS.read_text()
    fn = re.search(r"^def avocado_zram_compressor_module.*?(?=^\S)", src, re.S | re.M).group(0)
    ns = {}
    exec(fn, ns)
    return ns["avocado_zram_compressor_module"]


class ZramCompressorModule(unittest.TestCase):
    def setUp(self):
        self.module = _load()

    def test_l4t_68_crypto_module(self):
        # L4T 6.8: zram uses the crypto API, default lzo-rle, built =m.
        config = 'CONFIG_ZRAM=m\nCONFIG_ZRAM_DEF_COMP_LZORLE=y\nCONFIG_ZRAM_DEF_COMP="lzo-rle"\nCONFIG_CRYPTO_LZO=m\n'
        self.assertEqual(self.module(config), "lzo-rle")

    def test_618_builtin_backend(self):
        # linux-yocto 6.18: zram's own backend, nothing to ship.
        config = 'CONFIG_ZRAM=m\nCONFIG_ZRAM_BACKEND_LZO=y\nCONFIG_ZRAM_DEF_COMP_LZORLE=y\nCONFIG_ZRAM_DEF_COMP="lzo-rle"\nCONFIG_CRYPTO_LZO=y\n'
        self.assertIsNone(self.module(config))

    def test_no_zram(self):
        self.assertIsNone(self.module("# CONFIG_ZRAM is not set\n"))


if __name__ == "__main__":
    unittest.main()
