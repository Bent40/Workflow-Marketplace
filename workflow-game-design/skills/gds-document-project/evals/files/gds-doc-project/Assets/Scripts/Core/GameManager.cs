// Assets/Scripts/Core/GameManager.cs
// Central singleton that owns global game state and the run lifecycle.
// Persists across scene loads via DontDestroyOnLoad.
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Game.Core
{
    public enum GameState { Menu, Playing, Paused, GameOver }

    public class GameManager : MonoBehaviour
    {
        public static GameManager Instance { get; private set; }

        [SerializeField] private GameSettings settings;

        public GameState State { get; private set; } = GameState.Menu;
        public int Score { get; private set; }

        private void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(gameObject);
                return;
            }
            Instance = this;
            DontDestroyOnLoad(gameObject);
        }

        public void StartRun()
        {
            Score = 0;
            State = GameState.Playing;
            SceneManager.LoadScene(settings.GameplaySceneName);
        }

        public void AddScore(int points)
        {
            if (State != GameState.Playing) return;
            Score += points;
        }

        public void GameOver()
        {
            State = GameState.GameOver;
            SceneManager.LoadScene(settings.GameOverSceneName);
        }
    }
}
