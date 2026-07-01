// Assets/Scripts/Spinner.cs
// The entire project: one MonoBehaviour that rotates the object it is on.
using UnityEngine;

public class Spinner : MonoBehaviour
{
    [SerializeField] private float degreesPerSecond = 90f;

    private void Update()
    {
        transform.Rotate(0f, degreesPerSecond * Time.deltaTime, 0f);
    }
}
