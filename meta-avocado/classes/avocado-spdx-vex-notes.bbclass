# Status notes on the VEX statements of SPDX 3.0 documents, as OE-core writes
# them from wrynose on (oe/spdx30_task: Add status notes to VEX relationship,
# df6d882611f2): the CVE_STATUS detail on an Ignored statement, "detail:
# description" on a Patched or Unpatched one.
#
# scarthgap's create_spdx writes no notes, and the notes are the only place the
# reason survives into the SPDX. sbom-cve-check exports a statement's notes as
# the manifest's "detail", so without them an upstream-wontfix CVE reads as
# plain Ignored, and a Patched or Ignored CVE from a statement has no detail at
# all, which the report's consumer rejects.
#
# Done here rather than in the OE-core fork, which takes upstream rebases rather
# than carrying patches. A prefunc of do_create_spdx wraps the functions
# create_spdx calls, in the task's own process: _get_cves_info, which yields
# each CVE's status, and ObjectSet.new_cve_vuln and new_vex_*, whose results
# get the notes. The notes are the upstream change's; the statements keep the
# SPDX ids scarthgap gives them, where upstream also hashes the notes into the id.
#
# Inherited from kas/feature/sbom.yml and kas/feature/cve-check.yml alike: it
# changes do_create_spdx's signature, and a CVE scan stacked on a feed build
# has to share it to reuse the feed's SPDX.

python avocado_spdx_vex_notes() {
    avocado_spdx_vex_notes_install()
}
do_create_spdx[prefuncs] += "avocado_spdx_vex_notes"

def avocado_spdx_vex_notes_install():
    import oe.sbom30
    import oe.spdx30_tasks

    if getattr(oe.spdx30_tasks, "_avocado_vex_notes", False):
        return
    oe.spdx30_tasks._avocado_vex_notes = True

    statuses = {}
    vulns = []
    by_link = {}
    mapped = [0]

    get_cves_info = oe.spdx30_tasks._get_cves_info
    def cves_info(d):
        for cve_id, mapping, detail, description in get_cves_info(d):
            statuses[cve_id] = (detail, description)
            yield cve_id, mapping, detail, description
    oe.spdx30_tasks._get_cves_info = cves_info

    new_cve_vuln = oe.sbom30.ObjectSet.new_cve_vuln
    def cve_vuln(self, cve):
        v = new_cve_vuln(self, cve)
        vulns.append((v, cve))
        return v
    oe.sbom30.ObjectSet.new_cve_vuln = cve_vuln

    def status_of(from_):
        # create_spdx links each statement to one CVE by its alias, which is
        # set after new_cve_vuln returns, so the map is built on first use.
        if len(from_) != 1:
            return None
        if mapped[0] != len(vulns):
            by_link.update((oe.sbom30.get_element_link_id(v), c) for v, c in vulns)
            mapped[0] = len(vulns)
        return statuses.get(by_link.get(from_[0]))

    def with_notes(method, notes_of):
        def wrapper(self, from_, to, *args, **kwargs):
            rels = method(self, from_, to, *args, **kwargs)
            status = status_of(from_)
            notes = notes_of(*status) if status else None
            if notes:
                for r in rels:
                    r.security_statusNotes = notes
            return rels
        return wrapper

    joined = lambda detail, description: ": ".join(v for v in (detail, description) if v)
    ObjectSet = oe.sbom30.ObjectSet
    ObjectSet.new_vex_patched_relationship = with_notes(ObjectSet.new_vex_patched_relationship, joined)
    ObjectSet.new_vex_unpatched_relationship = with_notes(ObjectSet.new_vex_unpatched_relationship, joined)
    ObjectSet.new_vex_ignored_relationship = with_notes(
        ObjectSet.new_vex_ignored_relationship, lambda detail, description: detail)
