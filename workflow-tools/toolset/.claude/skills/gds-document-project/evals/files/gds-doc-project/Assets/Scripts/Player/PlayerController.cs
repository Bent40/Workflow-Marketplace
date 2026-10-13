// Assets/Scripts/Player/PlayerController.cs
// Drives the player avatar. Reads movement from input each frame but applies
// physics in FixedUpdate against the Rigidbody2D. Notifies GameManager on death.
using UnityEngine;
using Game.Core;

namespace Game.Player
{
    [RequireComponent(typeof(Rigidbody2D))]
    public class PlayerController : MonoBehaviour
    {
        [SerializeField] private GameSettings settings;

        private Rigidbody2D _body;
        private float _inputX;
        private bool _jumpQueued;

        private void Awake()
        {
            _body = GetComponent<Rigidbody2D>();
        }

        private void Update()
        {
            // Sample input in Update; never move the Rigidbody here.
            _inputX = Input.GetAxisRaw("Horizontal");
            if (Input.GetButtonDown("Jump")) _jumpQueued = true;
        }

        private void FixedUpdate()
        {
            var velocity = _body.velocity;
            velocity.x = _inputX * settings.MoveSpeed;
            if (_jumpQueued)
            {
                velocity.y = settings.JumpForce;
                _jumpQueued = false;
            }
            _body.velocity = velocity;
        }

        private void OnTriggerEnter2D(Collider2D other)
        {
            if (other.CompareTag("Hazard"))
            {
                GameManager.Instance.GameOver();
            }
        }
    }
}
