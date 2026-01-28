# Tegra targets need virtual/libgbm in DEPENDS for use_system_minigbm=true
# Mesa on Tegra provides virtual/libgbm via meta-tegra's mesa bbappend
DEPENDS:append:tegra = " virtual/libgbm"
