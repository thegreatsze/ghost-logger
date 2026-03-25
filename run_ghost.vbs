' run_ghost.vbs
' Launches Ghost Logger silently — no console window appears.
' Double-click this file to start the logger at login or on demand.

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")

' Get the directory this VBS file lives in
Dim scriptDir
scriptDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))

' Run pythonw (no console) with the ghost_logger script
WshShell.Run "pythonw """ & scriptDir & "ghost_logger.py""", 0, False

Set WshShell = Nothing
