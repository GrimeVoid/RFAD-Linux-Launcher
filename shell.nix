{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  name = "rfad-launcher-env";

  buildInputs = with pkgs; [
    (python3.withPackages (ps: with ps; [
      pyqt5
      pillow
    ]))
    libsForQt5.qtwayland
    libsForQt5.qtsvg

    innoextract
    p7zip
    xdg-utils

    gamemode
    mangohud
  ];

  shellHook = ''
    export QT_QPA_PLATFORM="wayland;xcb"
    export QT_PLUGIN_PATH="${pkgs.libsForQt5.qtwayland}/${pkgs.libsForQt5.qtbase.qtPluginPrefix}:${pkgs.libsForQt5.qtsvg}/${pkgs.libsForQt5.qtbase.qtPluginPrefix}:$QT_PLUGIN_PATH"
    
    echo "=========================================================="
    echo "  RFAD Launcher окружение готово!"
    echo "  Запуск: ./run.sh"
    echo "=========================================================="
  '';
}
