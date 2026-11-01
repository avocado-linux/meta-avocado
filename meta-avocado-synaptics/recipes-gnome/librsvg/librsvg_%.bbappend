# meta-synaptics' librsvg append removes gdkpixbuf (its :remove runs after
# its own :append), but newer librsvg also has a separate gdkpixbuf-loader
# option that needs it: meson stops with "Feature pixbuf-loader cannot be
# enabled". Drop the loader along with gdk-pixbuf.
PACKAGECONFIG:remove = "gdkpixbuf-loader"
