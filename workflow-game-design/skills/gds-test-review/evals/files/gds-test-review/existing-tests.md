# Existing Test Suite Snapshot — "Lantern Keep" (Unity, C#) — for review

This is the project's current automated test suite. Engine: Unity (NUnit + UnityTest).
Below are the test files verbatim plus the latest CI summary. Review the QUALITY and COVERAGE.

## CI summary (last 10 runs)
- Total tests: 14 (10 EditMode unit, 4 PlayMode).
- Pass rate: 12/14 consistently pass.
- `Smoke_NewGame_StartsSuccessfully` and `Wave_SpawnsEnemies_OnNight` FAIL intermittently (pass ~6/10 runs) — flagged by the team as flaky.
- Average durations: unit < 1s each; PlayMode 5-40s each. `Wave_SpawnsEnemies_OnNight` takes ~40s.

## File: tests/EditMode/DamageCalculatorTests.cs  (GOOD — leave alone)
```csharp
[TestFixture]
public class DamageCalculatorTests
{
    private DamageCalculator _sut;
    [SetUp] public void Setup() => _sut = new DamageCalculator();

    [Test] public void Calculate_InLight_NoBonus() =>
        Assert.AreEqual(100f, _sut.Calculate(100f, inDarkness:false));

    [Test] public void Calculate_InDarkness_AppliesBonus() =>
        Assert.AreEqual(150f, _sut.Calculate(100f, inDarkness:true));

    [TestCase(0f, false, 0f)]
    [TestCase(50f, true, 75f)]
    public void Calculate_Parameterized(float baseDmg, bool dark, float expected) =>
        Assert.AreEqual(expected, _sut.Calculate(baseDmg, dark));
}
```
This fixture is deterministic, isolated, fast, well-named, asserts real behavior, and
covers the light/darkness damage branches plus boundaries. No issues.

## File: tests/EditMode/CraftingRecipeTests.cs  (GOOD — leave alone)
```csharp
[TestFixture]
public class CraftingRecipeTests
{
    [Test] public void Craft_WithEnoughResources_Succeeds() {
        var sut = new CraftingSystem(wood:3, iron:2, ember:1);
        Assert.IsTrue(sut.TryCraft("Barricade"));
    }
    [Test] public void Craft_MissingResources_Fails() {
        var sut = new CraftingSystem(wood:0, iron:0, ember:0);
        Assert.IsFalse(sut.TryCraft("Barricade"));
    }
}
```
Deterministic and isolated; covers the recipe-gating happy and failure paths.

## File: tests/PlayMode/WaveTests.cs  (HAS PROBLEMS)
```csharp
public class WaveTests
{
    [UnityTest]
    public IEnumerator Wave_SpawnsEnemies_OnNight()
    {
        var go = new GameObject("WaveManager");
        var mgr = go.AddComponent<WaveManager>();
        mgr.StartNight();
        yield return new WaitForSeconds(35f);   // hard-coded wait; also why this is slow + flaky
        Assert.Greater(GameObject.FindObjectsOfType<Enemy>().Length, 0);
        // no cleanup of 'go' or spawned enemies
    }

    [UnityTest]
    public IEnumerator Wave_Manager_Initializes()
    {
        var go = new GameObject("WaveManager");
        go.AddComponent<WaveManager>();
        yield return null;
        // NO ASSERTION — does this test anything?
    }
}
```

## File: tests/PlayMode/SaveSmokeTests.cs  (HAS PROBLEMS)
```csharp
public class SaveSmokeTests
{
    static bool _seeded;   // shared static state across tests
    [UnityTest]
    public IEnumerator Smoke_NewGame_StartsSuccessfully()
    {
        if (!_seeded) { MetaProgression.Seed(); _seeded = true; }
        SceneManager.LoadScene("Game");
        yield return new WaitForSeconds(5f);   // hard-coded wait
        Assert.IsNotNull(GameObject.FindWithTag("Player"));
    }
}
```

## Coverage notes (from the team)
- Covered: damage calc, crafting recipes, wave spawning (flaky), new-game smoke.
- NOT covered at all: **meta-progression SAVE/LOAD roundtrip** (the highest data-integrity risk — losing permanent unlocks), and **Switch suspend/resume + save-during-suspend** certification behavior.
