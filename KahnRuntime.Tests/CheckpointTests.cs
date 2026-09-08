using System.Text.Json;
using KahnRuntime;

internal static class CheckpointTests
{
    public static void WriteFixture(string directory)
    {
        directory = Path.GetFullPath(directory);
        string path = Path.Combine(directory, "checkpoint.json");
        new RuntimeCheckpointStore(path).Save(new RuntimeCheckpointData
        {
            Version = 1,
            RuntimeState = "Running",
            RuntimeInstanceId = "offline-checkpoint-test",
            AuthorizationState = "NONE",
            CampaignPath = Path.Combine(directory, "campaign.json"),
            ControlPath = Path.Combine(directory, "control.json"),
            EvidencePath = Path.Combine(directory, "evidence.jsonl"),
            DecisionLogPath = Path.Combine(directory, "decisions.jsonl"),
            CheckpointPath = path,
        });
    }

    public static void RunAll()
    {
        string directory = Path.Combine(AppContext.BaseDirectory, "checkpoint-test-" + Guid.NewGuid().ToString("N"));
        string path = Path.Combine(directory, "checkpoint.json");
        DateTimeOffset before = DateTimeOffset.UtcNow;
        try
        {
            WriteFixture(directory);
            using (JsonDocument saved = JsonDocument.Parse(File.ReadAllText(path)))
            {
                JsonElement root = saved.RootElement;
                Require(root.GetProperty("version").GetInt32() == 2, "writer must emit schema 2, even before first dispatch");
                Require(root.GetProperty("campaign_id").ValueKind == JsonValueKind.Null, "fixture must have no campaign");
                Require(root.GetProperty("authorization_state").GetString() == "NONE", "saving must not authorize execution");
                Require(root.GetProperty("updated_utc").GetDateTimeOffset() >= before, "writer must refresh checkpoint time");
            }
            new RuntimeCheckpointStore(path).Save(new RuntimeCheckpointData
            {
                CampaignId = "watched-test",
                CampaignSchemaVersion = 2,
                AuthorizationState = "WATCH",
                RuntimeState = "Running",
            });
            using (JsonDocument saved = JsonDocument.Parse(File.ReadAllText(path)))
            {
                Require(saved.RootElement.GetProperty("version").GetInt32() == 2, "replacement save must remain schema 2");
                Require(saved.RootElement.GetProperty("campaign_id").GetString() == "watched-test", "replacement must reach disk");
                Require(!saved.RootElement.GetProperty("execution_authorized").GetBoolean(), "WATCH must remain unauthorized");
            }
            Require(!File.Exists(path + ".tmp"), "atomic save must not leave a temporary file");
            Console.WriteLine("PASS checkpoint disk round trips (2 cases)");
        }
        finally
        {
            if (File.Exists(path)) File.Delete(path);
            if (File.Exists(path + ".tmp")) File.Delete(path + ".tmp");
            if (Directory.Exists(directory)) Directory.Delete(directory);
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
