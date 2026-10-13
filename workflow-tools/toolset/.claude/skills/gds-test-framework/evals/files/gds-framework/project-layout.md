# Staged Unity project layout (treat these as the files present in the project)

This is a Unity project (engine detection should resolve to Unity). The relevant
files/directories that exist on disk:

```
ProjectSettings/ProjectVersion.txt        <- staged: m_EditorVersion 2022.3.21f1
ProjectSettings/ProjectSettings.asset      (exists)
Assets/
  Scenes/
    MainMenu.unity                          (exists)
    Game.unity                              (exists)
  Scripts/
    Combat/DamageCalculator.cs               (gameplay code, game assembly "Game")
    Player/PlayerController.cs               (gameplay code)
Game.asmdef                                  (the game's assembly definition, name: "Game")
```

NOTE: There is **no** `Assets/Tests/` folder, no `*.Tests.asmdef`, and no test
framework configured yet. This is a clean project with no existing test setup.
The game assembly that tests should reference is named **"Game"**.
