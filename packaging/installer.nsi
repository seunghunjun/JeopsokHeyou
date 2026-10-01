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
; Created by the running app (main.py) — lets the installer see that JeopsokHeyou is open
!define RUN_MUTEX "JeopsokHeyou.Running"

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
LangString AppRunning ${LANG_ENGLISH} "JeopsokHeyou is running.$\r$\n$\r$\nClose every JeopsokHeyou window, then click Retry.$\r$\n(Open connections and port forwards will be closed.)"
LangString AppRunning ${LANG_KOREAN} "JeopsokHeyou가 실행 중입니다.$\r$\n$\r$\n모든 JeopsokHeyou 창을 닫은 뒤 [다시 시도]를 누르세요.$\r$\n(열려 있는 접속과 포트 포워딩은 종료됩니다.)"
LangString AppRunning ${LANG_JAPANESE} "JeopsokHeyou が実行中です。$\r$\n$\r$\nすべての JeopsokHeyou のウィンドウを閉じてから [再試行] を押してください。$\r$\n(開いている接続とポート転送は終了します。)"
LangString DescApp ${LANG_ENGLISH} "The program files."
LangString DescApp ${LANG_KOREAN} "프로그램 파일입니다."
LangString DescApp ${LANG_JAPANESE} "プログラム本体のファイルです。"
LangString DescDesktop ${LANG_ENGLISH} "Put a JeopsokHeyou shortcut on the desktop."
LangString DescDesktop ${LANG_KOREAN} "바탕화면에 JeopsokHeyou 바로가기를 만듭니다."
LangString DescDesktop ${LANG_JAPANESE} "デスクトップに JeopsokHeyou のショートカットを作成します。"

; ---------------------------------------------------------------- running-app check
; Two signals: the mutex the app creates (1.0.2 and later), and the installed exe being locked
; (Windows keeps a running program's exe open, which also catches older versions without the mutex).
!macro CHECK_RUNNING_FUNC un
Function ${un}CheckRunning
  retry:
    StrCpy $R0 0
    System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "${RUN_MUTEX}") p.r1'
    StrCmp $1 0 check_file
      System::Call 'kernel32::CloseHandle(p r1)'
      StrCpy $R0 1
      Goto decide
  check_file:
    IfFileExists "$INSTDIR\${APP_EXE}" 0 decide
    ClearErrors
    FileOpen $2 "$INSTDIR\${APP_EXE}" a
    IfErrors 0 +3
      StrCpy $R0 1
      Goto decide
    FileClose $2
  decide:
    StrCmp $R0 1 0 done
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(AppRunning)" /SD IDCANCEL IDRETRY retry
    Abort
  done:
FunctionEnd
!macroend
!insertmacro CHECK_RUNNING_FUNC ""
!insertmacro CHECK_RUNNING_FUNC "un."

Section "!$(SecApp)" SEC_APP
  SectionIn RO
  ; The app may have been started while the wizard was open
  Call CheckRunning
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
  Call CheckRunning
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
  Call un.CheckRunning
FunctionEnd
