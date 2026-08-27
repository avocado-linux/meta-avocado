# Host build: do_merge_config runs a bare `python3 -c "... import yaml ..."`.
# On the host build PATH bare python3 resolves to the buildtools SDK python,
# which has no PyYAML, so the merge fails with ModuleNotFoundError. The recipe
# already DEPENDS on python3-pyyaml-native; inheriting python3native prepends
# the staged python3-native to PATH so bare python3 picks the native python
# that can import the staged yaml module.
inherit python3native
