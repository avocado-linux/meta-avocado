# SPDX-License-Identifier: Apache-2.0

# BitBake hashes an addpylib module's functions into task signatures only for
# the submodules named here: bb/parse/ast.py's PyLibNode.eval reads BBIMPORTS
# and calls bb.codeparser.add_module_functions once per entry. A submodule left
# out is invisible to every task hash, so editing it leaves sstate valid and
# ships the previously generated file.
BBIMPORTS = ["repoconf"]
