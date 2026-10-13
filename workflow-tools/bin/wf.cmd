@echo off
rem workflow-tools launcher for Windows (see bin/wf).
set WF_PROJECT_MODE=1
python "%~dp0..\toolset\scripts\wf" %*
