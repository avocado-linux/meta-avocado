// SPDX-License-Identifier: GPL-2.0
/*
 * avocado-shm: cacheable userspace mapping of one reserved memory region.
 *
 * Exists to replace an ivshmem PCI BAR for inter-VM shared memory. A BAR is
 * device memory: on arm64 mmap of /sys/bus/pci/.../resource2 is Device-nGnRE
 * and resource2_wc is Normal-NC, and neither can be cached, so a polling loop
 * pays an interconnect round trip per read. Measured on QCS9075: the same
 * ping-pong over write-back cacheable memory runs at p50 208 ns against
 * 7187 ns through the BAR.
 *
 * The region is genuine RAM, so leaving vma->vm_page_prot at its default in
 * remap_pfn_range() gives a Normal write-back cacheable mapping. Coherency
 * between the two guests is maintained by hardware; they are on one coherent
 * SoC and both map the same physical pages.
 *
 * Deliberately NOT /dev/mem. CONFIG_DEVMEM is bool, so it cannot be modular,
 * and the guest here runs the same kernel image as the host -- enabling it
 * would put arbitrary physical memory access in the host rootfs permanently,
 * and kernel lockdown would disable it anyway. This driver hands out exactly
 * one window, whose base and size come from the device tree, and rejects
 * everything else.
 */
#include <linux/module.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/mm.h>
#include <linux/of.h>
#include <linux/of_reserved_mem.h>
#include <linux/platform_device.h>

#define DRV_NAME "avocado-shm"

static phys_addr_t shm_base;
static resource_size_t shm_size;

static int shm_mmap(struct file *file, struct vm_area_struct *vma)
{
	size_t len = vma->vm_end - vma->vm_start;
	unsigned long off = (unsigned long)vma->vm_pgoff << PAGE_SHIFT;

	if (!shm_size)
		return -ENODEV;

	/* The bound that makes this safe: nothing outside the region, ever,
	 * and no integer overflow reaching the comparison.
	 */
	if (off >= shm_size || len > shm_size - off)
		return -EINVAL;

	/* No pgprot_noncached()/pgprot_writecombine() here on purpose -- the
	 * default is what makes the mapping cacheable, which is the point.
	 */
	return remap_pfn_range(vma, vma->vm_start,
			       (shm_base + off) >> PAGE_SHIFT,
			       len, vma->vm_page_prot);
}

static const struct file_operations shm_fops = {
	.owner = THIS_MODULE,
	.mmap  = shm_mmap,
	.llseek = noop_llseek,
};

static struct miscdevice shm_misc = {
	.minor = MISC_DYNAMIC_MINOR,
	.name  = DRV_NAME,
	.fops  = &shm_fops,
	.mode  = 0600,
};

static int shm_probe(struct platform_device *pdev)
{
	struct reserved_mem *rmem;
	struct device_node *np;
	int ret;

	np = of_parse_phandle(pdev->dev.of_node, "memory-region", 0);
	if (!np)
		return dev_err_probe(&pdev->dev, -EINVAL, "no memory-region phandle\n");

	rmem = of_reserved_mem_lookup(np);
	of_node_put(np);
	if (!rmem)
		return dev_err_probe(&pdev->dev, -EINVAL, "memory-region is not a reserved-memory node\n");

	if (!rmem->size || (rmem->base | rmem->size) & ~PAGE_MASK)
		return dev_err_probe(&pdev->dev, -EINVAL,
				     "region %pa+%pa is empty or not page aligned\n",
				     &rmem->base, &rmem->size);

	shm_base = rmem->base;
	shm_size = rmem->size;

	ret = misc_register(&shm_misc);
	if (ret)
		return dev_err_probe(&pdev->dev, ret, "misc_register failed\n");

	dev_info(&pdev->dev, "/dev/%s -> %pa + %pa, write-back cacheable\n",
		 DRV_NAME, &shm_base, &shm_size);
	return 0;
}

static void shm_remove(struct platform_device *pdev)
{
	misc_deregister(&shm_misc);
	shm_size = 0;
}

static const struct of_device_id shm_of_match[] = {
	{ .compatible = "avocado,shm" },
	{ }
};
MODULE_DEVICE_TABLE(of, shm_of_match);

static struct platform_driver shm_driver = {
	.probe  = shm_probe,
	.remove = shm_remove,
	.driver = {
		.name = DRV_NAME,
		.of_match_table = shm_of_match,
	},
};
module_platform_driver(shm_driver);

MODULE_DESCRIPTION("Cacheable userspace mapping of one reserved memory region");
MODULE_AUTHOR("Avocado Linux");
MODULE_LICENSE("GPL v2");
