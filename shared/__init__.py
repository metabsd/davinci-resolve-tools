"""
Shared utilities for DaVinci Resolve Tools.

This package is **only** intended to be imported from scripts that run with
DaVinci Resolve's embedded Python interpreter
(`C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\python.exe` on Windows,
`/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3`
on macOS, `/opt/resolve/bin/python3` on Linux).

It wraps the official DaVinciResolveScript API with a couple of helpers that
make tool scripts less verbose.
"""
