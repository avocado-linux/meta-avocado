# mesa 26 dropped the kmsro option; panfrost carries its own KMS-only support.
PACKAGECONFIG += "egl panfrost"
