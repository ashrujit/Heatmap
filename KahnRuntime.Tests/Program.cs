using KahnRuntime;
using System.Text.Json;

try
{
if (args.Length == 2 && args[0] == "write-checkpoint")
{
    CheckpointTests.WriteFixture(args[1]);
    return;
}
if (args.Length == 2 && args[0] == "validate-plan")
{
    var plan = CampaignPlanParser.Parse(File.ReadAllText(args[1]));
    Console.WriteLine(JsonSerializer.Serialize(new { schema = plan.SchemaVersion, roles = plan.Waypoints.Select(w => w.Role.ToString()),
        authorized = CampaignState.ForPlan(plan).ExecutionAuthorized }));
    return;
}
if (args.Length == 3 && args[0] == "session-replay")
{
    try { SessionReplay.Run(args[1], args[2]); }
    catch (Exception error) { Console.Error.WriteLine(error); Environment.ExitCode = 1; }
    return;
}
if (args.Length == 3 && args[0] == "replay")
{
    ScalingReplay.Run(args[1], args[2]);
    return;
}
if (args.Length != 0)
    throw new ArgumentException("Usage: KahnRuntime.Tests [replay input.jsonl output.jsonl]");
RuntimeSelfTests.RunAll();
Console.WriteLine("PASS existing RuntimeSelfTests (39 checks)");
ScalingTests.RunAll();
SessionTests.RunAll();
CheckpointTests.RunAll();
}
catch (Exception error)
{
    Console.Error.WriteLine(error);
    Environment.ExitCode = 1;
}
