@echo off
REM Claude Code multi-account launcher wrapper.
REM Place this in %USERPROFILE%\bin\ (ahead of %USERPROFILE%\.local\bin in PATH).
@python "%USERPROFILE%\.claude\launcher.py" %*
