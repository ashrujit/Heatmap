using System.Text.Json;
using KahnRuntime;
using KahnRuntime.Scaling;

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
            var key = new ClaimKey(EvidenceSource.LevelLedger, "root-epoch", "27");
            new RuntimeCheckpointStore(path).Save(new RuntimeCheckpointData
            {
                RootBinding = new(new(key, CampaignSide.Short, new(118133, 118145), RootClaimOrigin.Consumed,
                    before.AddMinutes(-2), before.AddMinutes(-1), before, EvidenceKind.RailHeld, null),
                    "separate-trigger", new(EvidenceSource.LevelLedger, "root-epoch", "32"), before, "fixture-only-pair"),
                RootOwnerHealth = "Tested", RootOwnerOrigin = "Consumed", RootEntryDistanceTicks = 129,
                LastRootAdmissionReason = "root_pair_unresolved", MaxRootEntryDistanceTicks = null,
            });
            using (JsonDocument saved = JsonDocument.Parse(File.ReadAllText(path)))
            {
                var root = saved.RootElement;
                var binding = root.GetProperty("root_binding");
                Require(binding.GetProperty("owner").GetProperty("key").GetProperty("rail_id").GetString() == "27", "owner identity lost");
                Require(binding.GetProperty("trigger_key").GetProperty("rail_id").GetString() == "32", "trigger replaced owner");
                Require(root.GetProperty("root_owner_origin").GetString() == "Consumed", "claim source not visible");
                Require(root.GetProperty("root_entry_distance_ticks").GetDouble() == 129, "entry distance lost");
                Require(root.GetProperty("max_root_entry_distance_ticks").ValueKind == JsonValueKind.Null, "unset cap manufactured");
            }
            Require(!File.Exists(path + ".tmp"), "atomic save must not leave a temporary file");
            Console.WriteLine("PASS checkpoint disk round trips (3 cases)");
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
