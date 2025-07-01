python __anonymous() {
    pn = d.getVar('PN')
    parallel_make_highmem_pn = d.getVar(f'PARALLEL_MAKE_HIGHMEM:pn-{pn}')
    if parallel_make_highmem_pn:
        d.setVar('PARALLEL_MAKE', parallel_make_highmem_pn)
    else:
        parallel_make_highmem = d.getVar('PARALLEL_MAKE_HIGHMEM')
        if parallel_make_highmem:
            d.setVar('PARALLEL_MAKE', parallel_make_highmem)
}
