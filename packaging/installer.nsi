; JeopsokHeyou installer (NSIS 3, Modern UI 2) — built by tools/build_release.py
; Defines passed on the command line: VERSION, SRC_DIR (PyInstaller output), OUT_FILE, ROOT
; Per-user install: no administrator rights needed, nothing written outside the user profile.

Unicode true
ManifestDPIAware true
SetCompressor /SOLID lzma
RequestExecutionLevel user

!include "MUI2.nsh"

!define APP_NAME "JeopsokHeyou"
!define APP_EXE "JeopsokHeyou.exe"
!define PUBLISHER "Seunghun Jun"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

Name "${APP_NAME} ${VERSION}"
OutFile "${OUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" "InstallDir"
BrandingText "${APP_NAME} ${VERSION}"

VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "FileDescription" "${APP_NAME} Setup"
VIAddVersionKey /LANG=1033 "CompanyName" "${PUBLISHER}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "(c) 2026 ${PUBLISHER}. GPL-3.0-or-later."

!define MUI_ICON "${ROOT}\assets\app.ico"
!define MUI_UNICON "${ROOT}\assets\app.ico"
!define MUI_ABORTWARNING
!define MUI_LANGDLL_ALLLANGUAGES
!define MUI_LANGDLL_REGISTRY_ROOT "HKCU"
!define MUI_LANGDLL_REGISTRY_KEY "Software\${APP_NAME}"
!define MUI_LANGDLL_REGISTRY_VALUENAME "InstallerLanguage"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${ROOT}\LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_COMPONENTS
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "Japanese"

LangString SecApp ${LANG_ENGLISH} "JeopsokHeyou (required)"
LangString SecApp ${LANG_KOREAN} "JeopsokHeyou (필수)"
LangString SecApp ${LANG_JAPANESE} "JeopsokHeyou（必須）"
LangString SecDesktop ${LANG_ENGLISH} "Desktop shortcut"
LangString SecDesktop ${LANG_KOREAN} "바탕화면 바로가기"
LangString SecDesktop ${LANG_JAPANESE} "デスクトップのショートカット"
LangString SecUnData ${LANG_ENGLISH} "Also delete my sessions and settings"
LangString SecUnData ${LANG_KOREAN} "세션과 설정도 함께 삭제"
LangString SecUnData ${LANG_JAPANESE} "セッションと設定も削除する"
LangString DescApp ${LANG_ENGLISH} "The program files."
LangString DescApp ${LANG_KOREAN} "프로그램 파일입니다."
LangString DescApp ${LANG_JAPANESE} "プログラム本体のファイルです。"
LangString DescDesktop ${LANG_ENGLISH} "Put a JeopsokHeyou shortcut on the desktop."
LangString DescDesktop ${LANG_KOREAN} "바탕화면에 JeopsokHeyou 바로가기를 만듭니다."
LangString DescDesktop ${LANG_JAPANESE} "デスクトップに JeopsokHeyou のショートカットを作成します。"

Section "!$(SecApp)" SEC_APP
  SectionIn RO
  ; Replace the previous version's bundled libraries instead of mixing old and new files
  RMDir /r "$INSTDIR\_internal"
  SetOutPath "$INSTDIR"
  File /r "${SRC_DIR}\*.*"

  ; Start the app in the language chosen for this installer (Settings can change it later)
  StrCpy $0 "en"
  StrCmp $LANGUAGE ${LANG_KOREAN} 0 +2
    StrCpy $0 "ko"
  StrCmp $LANGUAGE ${LANG_JAPANESE} 0 +2
    StrCpy $0 "ja"
  FileOpen $1 "$INSTDIR\installer-language" w
  FileWrite $1 $0
  FileClose $1

  CreateShortcut "$SMPROGRAMS\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  WriteRegStr HKCU "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "$(SecDesktop)" SEC_DESKTOP
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_APP} $(DescApp)
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP} $(DescDesktop)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function .onInit
  !insertmacro MUI_LANGDLL_DISPLAY
FunctionEnd

; ---------------------------------------------------------------- uninstaller
Section "un.${APP_NAME}" UNSEC_APP
  SectionIn RO
  ; Remove only what the installer put there — never the whole folder blindly
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\licenses"
  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\THIRD-PARTY-NOTICES.md"
  Delete "$INSTDIR\README.txt"
  Delete "$INSTDIR\installer-language"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${APP_NAME}.lnk"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\${APP_NAME}"
SectionEnd

Section /o "un.$(SecUnData)" UNSEC_DATA
  RMDir /r "$APPDATA\${APP_NAME}"
  RMDir /r "$TEMP\${APP_NAME}"
SectionEnd

Function un.onInit
  !insertmacro MUI_UNGETLANGUAGE
FunctionEnd
