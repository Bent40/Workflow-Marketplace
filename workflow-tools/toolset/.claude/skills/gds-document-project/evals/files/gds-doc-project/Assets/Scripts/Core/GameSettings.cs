// Assets/Scripts/Core/GameSettings.cs
// Tunable, designer-editable configuration as a ScriptableObject asset.
// Create instances via Assets > Create > Game > Settings. No magic numbers in
// gameplay scripts — they reference these fields instead.
using UnityEngine;

namespace Game.Core
{
    [CreateAssetMenu(fileName = "GameSettings", menuName = "Game/Settings")]
    public class GameSettings : ScriptableObject
    {
        [Header("Player Movement")]
        public float MoveSpeed = 6f;
        public float JumpForce = 12f;

        [Header("Scenes")]
        public string GameplaySceneName = "Gameplay";
        public string GameOverSceneName = "GameOver";
    }
}
