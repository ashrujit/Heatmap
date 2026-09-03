using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace KahnDispatcher;

internal sealed class MainForm : Form
{
    private readonly DispatcherSettings _settings;
    private readonly KahnctlClient _kahnctl;

    private ComboBox _runtimeProfile = null!;
    private Label _runtimeProfileDetail = null!;
    private RadioButton _longSide = null!;
    private RadioButton _shortSide = null!;
    private RadioButton _probeOnlyMode = null!;
    private RadioButton _scaleMode = null!;
    private TextBox _rootRange = null!;
    private TextBox _middleRange = null!;
    private TextBox _harvestRange = null!;
    private Label _runtimeStateTile = null!;
    private Label _preview = null!;
    private TextBox _baseQuantity = null!;
    private TextBox _scaleQuantity = null!;
    private TextBox _maxQuantity = null!;
    private TextBox _maxRetry = null!;
    private TextBox _ttlMinutes = null!;
    private CheckBox _retireExistingIfFlat = null!;
    private TextBox _notes = null!;
    private Label _statusLine = null!;
    private TextBox _output = null!;

    private bool _busy;
    private bool _loadingRuntimeProfile;
    private System.Windows.Forms.Timer? _sketchPollTimer;
    private DateTime _lastSketchWriteUtc = DateTime.MinValue;
    private string _lastSketchSignature = "";
    private string _statusText = "idle";
    private readonly ToolTip _toolTip = new();

    public MainForm()
    {
        _settings = DispatcherSettings.Load();
        _kahnctl = new KahnctlClient(_settings);
        BuildUi();
        ApplySettings();
        WireEvents();
        StartSketchDraftImport();
    }

    protected override async void OnShown(EventArgs e)
    {
        base.OnShown(e);
        await RunStatusAsync(silent: true);
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        SaveSettings();
        base.OnFormClosing(e);
    }

    private void BuildUi()
    {
        Text = "Kahn Dispatcher";
        Icon = AppIcon.Create();
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(620, 460);
        ClientSize = new Size(700, 520);
        AutoScaleMode = AutoScaleMode.Dpi;
        BackColor = Palette.Back;
        ForeColor = Palette.Fore;
        Font = new Font("Cascadia Mono", 9.0f, FontStyle.Regular, GraphicsUnit.Point);
        KeyPreview = true;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            BackColor = Palette.Back,
            Padding = new Padding(10),
            ColumnCount = 1,
            RowCount = 6,
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        Controls.Add(root);

        var profileRow = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            BackColor = Palette.Back,
            Margin = new Padding(0, 0, 0, 6),
        };
        root.Controls.Add(profileRow, 0, 0);

        profileRow.Controls.Add(PlainLabel("Profile", 50));
        _runtimeProfile = new ComboBox
        {
            DropDownStyle = ComboBoxStyle.DropDownList,
            Width = 96,
            BackColor = Palette.Input,
            ForeColor = Palette.Fore,
            FlatStyle = FlatStyle.Flat,
            Margin = new Padding(0, 0, 8, 0),
        };
        profileRow.Controls.Add(_runtimeProfile);
        _runtimeProfileDetail = new Label
        {
            AutoSize = false,
            Width = 330,
            Height = 24,
            ForeColor = Palette.Muted,
            BackColor = Palette.Back,
            Padding = new Padding(0, 3, 0, 0),
            TextAlign = ContentAlignment.MiddleLeft,
        };
        profileRow.Controls.Add(_runtimeProfileDetail);

        _runtimeStateTile = new Label
        {
            Text = "NO STATUS",
            AutoSize = false,
            Width = 124,
            Height = 24,
            BackColor = Palette.Unknown,
            ForeColor = Palette.Fore,
            BorderStyle = BorderStyle.FixedSingle,
            TextAlign = ContentAlignment.MiddleCenter,
            Margin = new Padding(0, 0, 0, 0),
        };
        profileRow.Controls.Add(_runtimeStateTile);
        _toolTip.SetToolTip(_runtimeStateTile, "Runtime state has not been read yet.");

        var form = new TableLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            BackColor = Palette.Back,
            ColumnCount = 6,
            RowCount = 5,
            Margin = new Padding(0, 0, 0, 6),
        };
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 58));
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 124));
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 64));
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 124));
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 64));
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 124));
        root.Controls.Add(form, 0, 1);

        AddLabel(form, "Side", 0, 0);
        _longSide = Radio("Long");
        _shortSide = Radio("Short");
        var sidePanel = RowPanel(_longSide, _shortSide);
        form.Controls.Add(sidePanel, 1, 0);

        AddLabel(form, "Mode", 2, 0);
        _probeOnlyMode = Radio("Probe only");
        _scaleMode = Radio("Scale");
        var modePanel = RowPanel(_probeOnlyMode, _scaleMode);
        form.Controls.Add(modePanel, 3, 0);
        form.SetColumnSpan(modePanel, 3);

        AddLabel(form, "Probe", 0, 1);
        _rootRange = Box("", 112);
        _rootRange.PlaceholderText = "7748-7756";
        form.Controls.Add(_rootRange, 1, 1);

        AddLabel(form, "Mid", 2, 1);
        _middleRange = Box("", 112);
        _middleRange.PlaceholderText = "7756.25-7772";
        form.Controls.Add(_middleRange, 3, 1);

        AddLabel(form, "Harvest", 4, 1);
        _harvestRange = Box("", 112);
        _harvestRange.PlaceholderText = "7772.25-7776";
        form.Controls.Add(_harvestRange, 5, 1);

        AddLabel(form, "Base", 0, 2);
        _baseQuantity = Box("2", 44);
        form.Controls.Add(_baseQuantity, 1, 2);

        AddLabel(form, "Scale", 2, 2);
        _scaleQuantity = Box("2", 44);
        form.Controls.Add(_scaleQuantity, 3, 2);

        AddLabel(form, "Max", 4, 2);
        _maxQuantity = Box("10", 44);
        form.Controls.Add(_maxQuantity, 5, 2);

        AddLabel(form, "Retry", 0, 3);
        _maxRetry = Box("3", 44);
        form.Controls.Add(_maxRetry, 1, 3);

        AddLabel(form, "TTL", 2, 3);
        _ttlMinutes = Box("30", 44);
        form.Controls.Add(_ttlMinutes, 3, 3);

        _retireExistingIfFlat = new CheckBox
        {
            Text = "replace flat",
            Checked = true,
            AutoSize = true,
            BackColor = Palette.Back,
            ForeColor = Palette.Fore,
            Margin = new Padding(0, 5, 0, 0),
        };
        form.Controls.Add(_retireExistingIfFlat, 4, 3);
        form.SetColumnSpan(_retireExistingIfFlat, 2);
        _toolTip.SetToolTip(_retireExistingIfFlat,
            "Allows replacement only when the existing Kahn campaign is Ready and flat.");

        AddLabel(form, "Notes", 0, 4);
        _notes = new TextBox
        {
            Width = 300,
            Height = 44,
            Multiline = true,
            ScrollBars = ScrollBars.Vertical,
            PlaceholderText = "notes",
            BackColor = Palette.Input,
            ForeColor = Palette.Fore,
            BorderStyle = BorderStyle.FixedSingle,
            Margin = new Padding(0, 2, 8, 6),
        };
        form.Controls.Add(_notes, 1, 4);
        form.SetColumnSpan(_notes, 3);

        _preview = new Label
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            ForeColor = Palette.Muted,
            BackColor = Palette.Back,
            Margin = new Padding(0, 2, 0, 6),
        };
        root.Controls.Add(_preview, 0, 2);

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            BackColor = Palette.Back,
            Margin = new Padding(0, 0, 0, 6),
        };
        root.Controls.Add(buttons, 0, 3);
        buttons.Controls.Add(CommandButton("Status", async (_, _) => await RunStatusAsync()));
        buttons.Controls.Add(CommandButton("Validate", async (_, _) => await RunDraftAsync(dryRun: true)));
        buttons.Controls.Add(CommandButton("Dispatch", async (_, _) => await RunDraftAsync(dryRun: false)));
        buttons.Controls.Add(CommandButton("Cancel", async (_, _) => await RunCancelAsync()));
        buttons.Controls.Add(CommandButton("FLAT", async (_, _) => await RunFlatAsync(), danger: true));
        buttons.Controls.Add(CommandButton("Clear", (_, _) => ClearEntryFields()));

        _statusLine = new Label
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            ForeColor = Palette.Muted,
            BackColor = Palette.Back,
            Margin = new Padding(0, 0, 0, 4),
        };
        root.Controls.Add(_statusLine, 0, 4);

        _output = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Vertical,
            BackColor = Palette.Output,
            ForeColor = Palette.Fore,
            BorderStyle = BorderStyle.FixedSingle,
            WordWrap = false,
        };
        root.Controls.Add(_output, 0, 5);
    }

    private void WireEvents()
    {
        _runtimeProfile.SelectedIndexChanged += RuntimeProfile_SelectedIndexChanged;
        _longSide.CheckedChanged += (_, _) => UpdatePreview();
        _shortSide.CheckedChanged += (_, _) => UpdatePreview();
        _probeOnlyMode.CheckedChanged += (_, _) => UpdatePreview();
        _scaleMode.CheckedChanged += (_, _) => UpdatePreview();
        _rootRange.TextChanged += (_, _) => UpdatePreview();
        _middleRange.TextChanged += (_, _) => UpdatePreview();
        _harvestRange.TextChanged += (_, _) => UpdatePreview();
        _baseQuantity.TextChanged += (_, _) => UpdatePreview();
        _scaleQuantity.TextChanged += (_, _) => UpdatePreview();
        _maxQuantity.TextChanged += (_, _) => UpdatePreview();
        _maxRetry.TextChanged += (_, _) => UpdatePreview();
        _ttlMinutes.TextChanged += (_, _) => UpdatePreview();
        KeyDown += MainForm_KeyDown;
    }

    private async void RuntimeProfile_SelectedIndexChanged(object? sender, EventArgs e)
    {
        if (_loadingRuntimeProfile)
            return;
        if (_busy)
        {
            SelectRuntimeProfile(_settings.ActiveProfile);
            ShowOutput("busy", "runtime profile cannot change while a command is running");
            return;
        }

        string profileName = SelectedRuntimeProfileName();
        if (!_settings.TrySelectRuntimeProfile(profileName))
            return;

        _lastSketchSignature = "";
        PrimeSketchDraftImportCursor();
        UpdateRuntimeProfileChrome();
        SaveSettings();
        await RunStatusAsync(silent: true);
    }

    private async void MainForm_KeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Control && e.KeyCode == Keys.Enter)
        {
            e.SuppressKeyPress = true;
            await RunDraftAsync(dryRun: false);
        }
        else if (e.Control && e.KeyCode == Keys.Delete)
        {
            e.SuppressKeyPress = true;
            await RunCancelAsync();
        }
        else if (e.KeyCode == Keys.F5)
        {
            e.SuppressKeyPress = true;
            await RunDraftAsync(dryRun: true);
        }
        else if (e.KeyCode == Keys.F9)
        {
            e.SuppressKeyPress = true;
            await RunStatusAsync();
        }
    }

    private async Task RunStatusAsync(bool silent = false)
    {
        if (_busy)
            return;

        List<string> args = RuntimeCommand("status");
        CommandResult result = await RunCommandAsync("status", args, silent);
        UpdateRuntimeStateTile("status", result);
        if (!silent)
            ShowOutput(OutputLabel("status", result.ExitCode), FormatCommandResult("status", result));
    }

    private async Task RunDraftAsync(bool dryRun)
    {
        if (_busy)
            return;

        KahnCommand command;
        try
        {
            command = BuildKahnCommand(dryRun);
        }
        catch (InputException ex)
        {
            ShowOutput("input", ex.Message);
            return;
        }

        if (!dryRun)
        {
            string confirmText = "Dispatch active Kahn campaign?"
                + Environment.NewLine
                + CommandSummary(command);
            if (!Confirm(confirmText, defaultYes: false))
                return;
        }

        string action = dryRun ? "validate" : "dispatch";
        CommandResult result = await RunCommandAsync(action, command.Arguments, silent: false);
        string displayText = FormatCommandResult(action, result);
        if (!dryRun && IsPreflightUnsafeRejection(result))
        {
            CommandResult preflight = await RunCommandAsync("preflight", RuntimeCommand("preflight"), silent: true);
            UpdateRuntimeStateTile("preflight", preflight);
            displayText += Environment.NewLine
                + Environment.NewLine
                + "Preflight"
                + Environment.NewLine
                + FormatCommandResult("preflight", preflight);
        }
        ShowOutput(OutputLabel(action, result.ExitCode), displayText);

        if (!dryRun && result.ExitCode == 0)
            await RunStatusAsync(silent: true);
    }

    private async Task RunCancelAsync()
    {
        if (_busy)
            return;
        if (!Confirm($"Issue CANCEL for {_settings.ActiveProfile}? Kahn will reject if exposure exists.", defaultYes: false))
            return;

        List<string> args = RuntimeCommand("cancel");
        args.Add("--reason");
        args.Add(BuildNotesOrDefault("KahnDispatcher CANCEL"));
        CommandResult result = await RunCommandAsync("cancel", args, silent: false);
        ShowOutput(OutputLabel("cancel", result.ExitCode), FormatCommandResult("cancel", result));
        if (result.ExitCode == 0)
            await RunStatusAsync(silent: true);
    }

    private async Task RunFlatAsync()
    {
        if (_busy)
            return;
        if (!Confirm($"Issue FLAT for {_settings.ActiveProfile}'s bound Kahn account/symbol?", defaultYes: false))
            return;

        List<string> args = RuntimeCommand("flat");
        args.Add("--reason");
        args.Add(BuildNotesOrDefault("KahnDispatcher FLAT"));
        CommandResult result = await RunCommandAsync("flat", args, silent: false);
        ShowOutput(OutputLabel("flat", result.ExitCode), FormatCommandResult("flat", result));
        if (result.ExitCode == 0)
            await RunStatusAsync(silent: true);
    }

    private async Task<CommandResult> RunCommandAsync(string label, IReadOnlyList<string> args, bool silent)
    {
        SetBusy(true, label);
        try
        {
            CommandResult result = await _kahnctl.RunAsync(args);
            if (!silent)
                SaveSettings();
            return result;
        }
        finally
        {
            SetBusy(false, "idle");
        }
    }

    private KahnCommand BuildKahnCommand(bool dryRun)
    {
        ResolvedRange root = ParseRange(_rootRange.Text, "root");
        ResolvedRange middle = ParseRange(_middleRange.Text, "middle");
        ResolvedRange harvest = ParseRange(_harvestRange.Text, "harvest");
        string side = _shortSide.Checked ? "short" : "long";
        ValidateDirectionalGeometry(side, root, middle, harvest);

        ResolvedRange arena = Envelope(Envelope(root, middle), harvest);
        bool scaleAllowed = _scaleMode.Checked;
        int baseQty = ParseIntBox(_baseQuantity, "base", 1, 100);
        int scaleQty = ParseIntBox(_scaleQuantity, "scale", 1, 100);
        int visibleMax = ParseIntBox(_maxQuantity, "max", 1, 100);
        int outgoingMax = scaleAllowed ? visibleMax : baseQty;
        if (scaleAllowed && outgoingMax <= baseQty)
            throw new InputException("scale mode requires Max greater than Base");

        List<string> args = RuntimeCommand("new-draft");
        args.Add("--side");
        args.Add(side);
        args.Add("--arena");
        args.Add(FormatRangeArg(arena));
        args.Add("--probe");
        args.Add(FormatRangeArg(root));
        if (scaleAllowed)
        {
            args.Add("--no-add");
            args.Add(FormatRangeArg(root));
            args.Add("--press");
            args.Add(FormatRangeArg(middle));
        }
        args.Add("--target");
        args.Add(FormatRangeArg(harvest));
        args.Add("--passive-harvest");
        args.Add(FormatRangeArg(harvest));
        args.Add("--scale-mode");
        args.Add(scaleAllowed ? "scale_allowed" : "root_only");
        args.Add("--probe-qty");
        args.Add(baseQty.ToString(CultureInfo.InvariantCulture));
        args.Add("--add-qty");
        args.Add(scaleQty.ToString(CultureInfo.InvariantCulture));
        args.Add("--max-qty");
        args.Add(outgoingMax.ToString(CultureInfo.InvariantCulture));
        args.Add("--max-retry");
        args.Add(ParseIntBox(_maxRetry, "retry", 1, 20).ToString(CultureInfo.InvariantCulture));
        args.Add("--ttl-minutes");
        args.Add(ParseIntBox(_ttlMinutes, "ttl", 1, 480).ToString(CultureInfo.InvariantCulture));
        args.Add("--summary-only");

        string notes = BuildNotes();
        if (!string.IsNullOrWhiteSpace(notes))
        {
            args.Add("--notes");
            args.Add(notes);
        }

        if (dryRun)
        {
            args.Add("--dry-run");
        }
        else
        {
            args.Add("--dispatch");
            args.Add("--activate");
            if (_retireExistingIfFlat.Checked)
                args.Add("--retire-existing-if-flat");
        }

        return new KahnCommand(
            args,
            side,
            root,
            middle,
            harvest,
            arena,
            scaleAllowed ? "scale_allowed" : "root_only",
            baseQty,
            scaleQty,
            outgoingMax,
            visibleMax);
    }

    private List<string> RuntimeCommand(string command)
    {
        var args = new List<string> { command };
        RuntimeProfile profile = _settings.ActiveRuntimeProfile();
        if (UseNamedProfile(profile))
        {
            args.Add(profile.Name.ToUpperInvariant());
        }
        else
        {
            args.Add("--runtime-dir");
            args.Add(profile.RuntimeDir);
        }
        return args;
    }

    private static bool UseNamedProfile(RuntimeProfile profile)
    {
        string name = profile.Name.ToUpperInvariant();
        string expected = name switch
        {
            "DEFAULT" => DispatcherSettings.DefaultRuntimeDir,
            "ES" => Path.Combine(DispatcherSettings.DefaultRuntimeDir, "ES"),
            "NQ" => Path.Combine(DispatcherSettings.DefaultRuntimeDir, "NQ"),
            _ => "",
        };
        return expected.Length > 0
            && SamePath(expected, profile.RuntimeDir);
    }

    private void UpdatePreview()
    {
        try
        {
            KahnCommand command = BuildKahnCommand(dryRun: true);
            string maxText = command.Mode == "root_only" && command.OutgoingMax != command.VisibleMax
                ? $"{command.OutgoingMax} sent, {command.VisibleMax} visible"
                : command.OutgoingMax.ToString(CultureInfo.InvariantCulture);
            _preview.Text =
                $"{command.Side.ToUpperInvariant()} probe {command.Root} -> mid {command.Middle} -> harvest {command.Harvest} | "
                + $"arena {command.Arena} | {command.Mode} | "
                + $"base {command.BaseQty} scale {command.ScaleQty} max {maxText}";
        }
        catch (InputException ex)
        {
            _preview.Text = ex.Message;
        }
    }

    private static void ValidateDirectionalGeometry(
        string side,
        ResolvedRange root,
        ResolvedRange middle,
        ResolvedRange harvest)
    {
        if (side == "long")
        {
            if (middle.Lower < root.Upper)
                throw new InputException("long middle must be at or above the probe range");
            if (harvest.Lower < middle.Upper)
                throw new InputException("long harvest must be at or above the middle range");
            return;
        }

        if (middle.Upper > root.Lower)
            throw new InputException("short middle must be at or below the probe range");
        if (harvest.Upper > middle.Lower)
            throw new InputException("short harvest must be at or below the middle range");
    }

    private static string CommandSummary(KahnCommand command)
    {
        string maxText = command.Mode == "root_only" && command.OutgoingMax != command.VisibleMax
            ? $"{command.OutgoingMax} (Max field {command.VisibleMax} ignored)"
            : command.OutgoingMax.ToString(CultureInfo.InvariantCulture);
        return $"{command.Side.ToUpperInvariant()} {command.Mode}"
            + Environment.NewLine
            + $"Probe: {command.Root}"
            + Environment.NewLine
            + $"Middle: {command.Middle}"
            + Environment.NewLine
            + $"Harvest: {command.Harvest}"
            + Environment.NewLine
            + $"Arena: {command.Arena}"
            + Environment.NewLine
            + $"Qty: base {command.BaseQty}, scale {command.ScaleQty}, max {maxText}";
    }

    private static string FormatCommandResult(string label, CommandResult result)
    {
        if (!TryParseJson(result.Output, out JsonDocument? document) || document is null)
            return result.DisplayText;

        using (document)
        {
            JsonElement root = document.RootElement;
            if (TryGetBool(root, "ok", out bool ok) && !ok)
            {
                return "Error: " + Str(root, "error")
                    + RawSuffix(result.Error);
            }

            return label switch
            {
                "status" => FormatStatus(root),
                "preflight" => FormatPreflight(root),
                "validate" or "dispatch" => FormatDraftResult(root, result),
                "cancel" or "flat" => FormatControlResult(root, result),
                _ => root.ToString() + RawSuffix(result.Error),
            };
        }
    }

    private static string FormatStatus(JsonElement root)
    {
        if (TryGetBool(root, "ok", out bool ok) && !ok)
            return "Status unavailable: " + Str(root, "error");

        var lines = new List<string>
        {
            $"Profile: {Str(root, "profile")} | runtime {Str(root, "runtime_state")}",
            $"Campaign: {Str(root, "campaign_id", "-")} | {Str(root, "campaign_status", "-")} | phase {Str(root, "phase", "-")}",
        };

        if (root.TryGetProperty("symbol_account", out JsonElement sym)
            && sym.ValueKind == JsonValueKind.Object)
        {
            lines.Add($"Symbol: {Str(sym, "execution_symbol", "-")} from {Str(sym, "market_data_symbol", "-")} | account {Str(sym, "account", "-")}");
        }
        else if (root.TryGetProperty("instance", out JsonElement instance)
            && instance.ValueKind == JsonValueKind.Object)
        {
            lines.Add($"Symbol: {Str(instance, "execution_symbol", "-")} from {Str(instance, "market_data_symbol", "-")} | account {Str(instance, "account", "-")}");
        }

        if (root.TryGetProperty("position", out JsonElement position)
            && position.ValueKind == JsonValueKind.Object)
        {
            string quantityText = Str(position, "quantity", "0");
            bool flat = Bool(position, "flat");
            if (!flat
                && double.TryParse(quantityText, NumberStyles.Float, CultureInfo.InvariantCulture, out double quantity))
            {
                flat = Math.Abs(quantity) < 0.000001;
            }
            lines.Add($"Position: {(flat ? "flat" : Str(position, "direction", "?"))} qty {quantityText} avg {Str(position, "average_price", "0")}");
        }

        if (root.TryGetProperty("warnings", out JsonElement warnings)
            && warnings.ValueKind == JsonValueKind.Array
            && warnings.GetArrayLength() > 0)
        {
            lines.Add("Warnings: " + string.Join(", ", warnings.EnumerateArray().Select(item => item.ToString())));
        }

        if (root.TryGetProperty("safe", out JsonElement safe)
            && safe.ValueKind == JsonValueKind.Object)
        {
            lines.Add($"Safe: dispatch={Bool(safe, "dispatch")} cancel={Bool(safe, "cancel")}");
        }

        if (root.TryGetProperty("control", out JsonElement control)
            && control.ValueKind == JsonValueKind.Object)
        {
            lines.Add($"Control: last {Str(control, "last_action", "-")}:{Str(control, "last_status", "-")}");
        }

        return string.Join(Environment.NewLine, lines);
    }

    private static string FormatPreflight(JsonElement root)
    {
        var lines = new List<string>
        {
            $"Runtime: running={Bool(root, "runtime_running")} fresh={Bool(root, "checkpoint_fresh")} paths={Bool(root, "correct_paths")}",
            $"Phase: {Str(root, "phase", "-")} | stale_control_file={Bool(root, "stale_control_file")}",
        };

        if (root.TryGetProperty("position", out JsonElement position)
            && position.ValueKind == JsonValueKind.Object)
        {
            string quantityText = Str(position, "quantity", "0");
            bool flat = Bool(position, "flat");
            lines.Add($"Position: flat={flat} qty {quantityText} avg {Str(position, "average_price", "0")}");
        }

        if (root.TryGetProperty("active_campaign", out JsonElement active)
            && active.ValueKind == JsonValueKind.Object)
        {
            lines.Add($"Active: present={Bool(active, "present")} id {Str(active, "id", "-")} status {Str(active, "status", "-")}");
        }

        if (root.TryGetProperty("safe", out JsonElement safe)
            && safe.ValueKind == JsonValueKind.Object)
        {
            lines.Add($"Safe: dispatch={Bool(safe, "dispatch")} cancel={Bool(safe, "cancel")}");
        }

        if (root.TryGetProperty("symbol_account", out JsonElement sym)
            && sym.ValueKind == JsonValueKind.Object)
        {
            lines.Add($"Symbol: {Str(sym, "execution_symbol", "-")} from {Str(sym, "market_data_symbol", "-")} | account {Str(sym, "account", "-")}");
        }

        return string.Join(Environment.NewLine, lines);
    }

    private static string FormatDraftResult(JsonElement root, CommandResult result)
    {
        var lines = new List<string>
        {
            $"Profile: {Str(root, "profile")} | runtime {Str(root, "runtime_dir")}",
        };

        if (Bool(root, "dry_run"))
            lines.Add("Outcome: validated");
        else
            lines.Add($"Outcome: wrote {Str(root, "campaign_path")}");

        if (root.TryGetProperty("summary", out JsonElement summary)
            && summary.ValueKind == JsonValueKind.Object)
        {
            lines.Add($"Campaign: {Str(summary, "id")} | {Str(summary, "status")} | {Str(summary, "side")}");
            lines.Add($"Window: {Str(summary, "not_before")} -> {Str(summary, "expires_at")}");
            lines.Add($"Sizing: {Str(summary, "scale_mode")} base {Str(summary, "probe_quantity")} add {Str(summary, "add_quantity")} max {Str(summary, "max_position_quantity")} retry {Str(summary, "max_retry")}");
            lines.Add($"Waypoints: {Str(summary, "waypoint_count")}");
        }

        if (root.TryGetProperty("prior_campaign", out JsonElement prior)
            && prior.ValueKind == JsonValueKind.Object)
        {
            lines.Add($"Prior: {Str(prior, "id")} | {Str(prior, "phase")} | {Str(prior, "action")}");
        }

        string backup = Str(root, "backup_path", "");
        if (!string.IsNullOrWhiteSpace(backup))
            lines.Add($"Backup: {backup}");
        string controlBackup = Str(root, "control_backup_path", "");
        if (!string.IsNullOrWhiteSpace(controlBackup))
            lines.Add($"Control archive: {controlBackup}");

        return string.Join(Environment.NewLine, lines) + RawSuffix(result.Error);
    }

    private static string FormatControlResult(JsonElement root, CommandResult result)
    {
        var lines = new List<string>
        {
            $"Profile: {Str(root, "profile")} | {Str(root, "action")}",
            $"Control: {Str(root, "control_id")}",
            $"Path: {Str(root, "control_path")}",
        };
        return string.Join(Environment.NewLine, lines) + RawSuffix(result.Error);
    }

    private void ApplySettings()
    {
        LoadRuntimeProfiles();
        _settings.TrySelectRuntimeProfile(SelectedRuntimeProfileName());
        UpdateRuntimeProfileChrome();

        _rootRange.Text = _settings.RootRange;
        _middleRange.Text = _settings.MiddleRange;
        _harvestRange.Text = _settings.HarvestRange;
        _baseQuantity.Text = Clamp(_settings.BaseQuantity, 1, 100).ToString(CultureInfo.InvariantCulture);
        _scaleQuantity.Text = Clamp(_settings.ScaleQuantity, 1, 100).ToString(CultureInfo.InvariantCulture);
        _maxQuantity.Text = Clamp(_settings.MaxQuantity, 1, 100).ToString(CultureInfo.InvariantCulture);
        _maxRetry.Text = Clamp(_settings.MaxRetry, 1, 20).ToString(CultureInfo.InvariantCulture);
        _ttlMinutes.Text = Clamp(_settings.TtlMinutes, 1, 480).ToString(CultureInfo.InvariantCulture);
        _retireExistingIfFlat.Checked = _settings.RetireExistingIfFlat;
        _notes.Text = _settings.Notes;

        if (_settings.Side.Equals("short", StringComparison.OrdinalIgnoreCase))
            _shortSide.Checked = true;
        else
            _longSide.Checked = true;

        if (_settings.ScaleMode.Equals("scale_allowed", StringComparison.OrdinalIgnoreCase))
            _scaleMode.Checked = true;
        else
            _probeOnlyMode.Checked = true;

        UpdatePreview();
    }

    private void SaveSettings()
    {
        _settings.TrySelectRuntimeProfile(SelectedRuntimeProfileName());
        _settings.Side = _shortSide.Checked ? "short" : "long";
        _settings.ScaleMode = _scaleMode.Checked ? "scale_allowed" : "root_only";
        _settings.RootRange = _rootRange.Text;
        _settings.MiddleRange = _middleRange.Text;
        _settings.HarvestRange = _harvestRange.Text;
        _settings.BaseQuantity = ReadIntOr(_baseQuantity, _settings.BaseQuantity, 1, 100);
        _settings.ScaleQuantity = ReadIntOr(_scaleQuantity, _settings.ScaleQuantity, 1, 100);
        _settings.MaxQuantity = ReadIntOr(_maxQuantity, _settings.MaxQuantity, 1, 100);
        _settings.MaxRetry = ReadIntOr(_maxRetry, _settings.MaxRetry, 1, 20);
        _settings.TtlMinutes = ReadIntOr(_ttlMinutes, _settings.TtlMinutes, 1, 480);
        _settings.RetireExistingIfFlat = _retireExistingIfFlat.Checked;
        _settings.Notes = _notes.Text;
        _settings.Save();
    }

    private void LoadRuntimeProfiles()
    {
        _loadingRuntimeProfile = true;
        try
        {
            _runtimeProfile.Items.Clear();
            foreach (RuntimeProfile profile in _settings.RuntimeProfiles)
                _runtimeProfile.Items.Add(profile.Name);
            SelectRuntimeProfile(_settings.ActiveProfile);
            if (_runtimeProfile.SelectedIndex < 0 && _runtimeProfile.Items.Count > 0)
                _runtimeProfile.SelectedIndex = 0;
        }
        finally
        {
            _loadingRuntimeProfile = false;
        }
    }

    private void SelectRuntimeProfile(string profileName)
    {
        _loadingRuntimeProfile = true;
        try
        {
            int index = -1;
            for (int i = 0; i < _runtimeProfile.Items.Count; i++)
            {
                if (string.Equals(_runtimeProfile.Items[i]?.ToString(), profileName, StringComparison.OrdinalIgnoreCase))
                {
                    index = i;
                    break;
                }
            }
            if (index >= 0)
                _runtimeProfile.SelectedIndex = index;
        }
        finally
        {
            _loadingRuntimeProfile = false;
        }
    }

    private string SelectedRuntimeProfileName()
        => _runtimeProfile.SelectedItem?.ToString() ?? _settings.ActiveProfile;

    private void UpdateRuntimeProfileChrome()
    {
        RuntimeProfile profile = _settings.ActiveRuntimeProfile();
        Text = $"Kahn Dispatcher - {profile.Name}";
        _runtimeProfileDetail.Text = $"dir: {AbbrevPath(profile.RuntimeDir)} | sketch: {AbbrevPath(profile.SketchDraftPath)}";
        SetStatusText(_statusText);
    }

    private void StartSketchDraftImport()
    {
        _sketchPollTimer = new System.Windows.Forms.Timer { Interval = 350 };
        _sketchPollTimer.Tick += (_, _) => PollSketchDraft();
        PrimeSketchDraftImportCursor();
        _sketchPollTimer.Start();
    }

    private void PrimeSketchDraftImportCursor()
    {
        try
        {
            string path = ExpandSketchDraftPath();
            if (path.Length > 0 && File.Exists(path))
                _lastSketchWriteUtc = File.GetLastWriteTimeUtc(path);
        }
        catch (Exception ex) when (ex is ArgumentException or IOException or NotSupportedException
            or PathTooLongException or UnauthorizedAccessException)
        {
        }
    }

    private void PollSketchDraft()
    {
        if (_busy)
            return;

        string path;
        try
        {
            path = ExpandSketchDraftPath();
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            return;
        }

        if (path.Length == 0 || !File.Exists(path))
            return;

        DateTime writeUtc;
        string text;
        try
        {
            writeUtc = File.GetLastWriteTimeUtc(path);
            if (writeUtc <= _lastSketchWriteUtc)
                return;
            text = File.ReadAllText(path);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return;
        }

        _lastSketchWriteUtc = writeUtc;
        if (!TryParseSketchImport(text, out SketchImport import))
            return;
        if (string.Equals(import.Signature, _lastSketchSignature, StringComparison.Ordinal))
            return;

        ApplySketchImport(import);
        _lastSketchSignature = import.Signature;
    }

    private string ExpandSketchDraftPath()
    {
        string configured = _settings.SketchDraftPath;
        if (string.IsNullOrWhiteSpace(configured))
            configured = Path.Combine(_settings.RuntimeDir, "saavik-probe.json");
        string expanded = Environment.ExpandEnvironmentVariables(configured);
        return string.IsNullOrWhiteSpace(expanded) ? "" : Path.GetFullPath(expanded);
    }

    private void ApplySketchImport(SketchImport import)
    {
        if (import.Side == "short")
            _shortSide.Checked = true;
        else
            _longSide.Checked = true;

        _rootRange.Text = $"{FormatArg(import.Root.Lower)}-{FormatArg(import.Root.Upper)}";
        _middleRange.Text = $"{FormatArg(import.Middle.Lower)}-{FormatArg(import.Middle.Upper)}";
        _harvestRange.Text = $"{FormatArg(import.Harvest.Lower)}-{FormatArg(import.Harvest.Upper)}";
        UpdatePreview();
        SetStatusText($"sketch {import.Side.ToUpperInvariant()} probe {import.Root} mid {import.Middle} harvest {import.Harvest}");
    }

    private static bool TryParseSketchImport(string text, out SketchImport import)
    {
        import = new SketchImport("", default, default, default, "");
        try
        {
            using JsonDocument document = JsonDocument.Parse(text);
            JsonElement root = document.RootElement;
            if (!TryGetString(root, "status", out string status)
                || !status.Equals("ok", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }
            if (!TryGetObject(root, "active_draft", out JsonElement draft))
                return false;
            if (!TryGetString(draft, "side", out string side))
                return false;
            side = side.Trim().ToLowerInvariant();
            if (side is not ("long" or "short"))
                return false;

            if (!TryGetRange(draft, "root_range", out ResolvedRange rootRange)
                && !TryGetRange(draft, "order_context_range", out rootRange))
            {
                return false;
            }
            if (!TryGetRange(draft, "middle_range", out ResolvedRange middleRange)
                && !TryGetRange(draft, "scale_range", out middleRange)
                && !TryGetRange(draft, "evaluate_range", out middleRange))
            {
                return false;
            }
            if (!TryGetRange(draft, "harvest_range", out ResolvedRange harvestRange)
                && !TryGetRange(draft, "target_range", out harvestRange))
            {
                return false;
            }

            ValidateDirectionalGeometry(side, rootRange, middleRange, harvestRange);
            string generatedAt = TryGetString(root, "generated_at_utc", out string value) ? value : "";
            string signature = string.Join("|",
                generatedAt,
                side,
                rootRange.Lower.ToString("R", CultureInfo.InvariantCulture),
                rootRange.Upper.ToString("R", CultureInfo.InvariantCulture),
                middleRange.Lower.ToString("R", CultureInfo.InvariantCulture),
                middleRange.Upper.ToString("R", CultureInfo.InvariantCulture),
                harvestRange.Lower.ToString("R", CultureInfo.InvariantCulture),
                harvestRange.Upper.ToString("R", CultureInfo.InvariantCulture));
            import = new SketchImport(side, rootRange, middleRange, harvestRange, signature);
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
        catch (InputException)
        {
            return false;
        }
    }

    private void ClearEntryFields()
    {
        _rootRange.Clear();
        _middleRange.Clear();
        _harvestRange.Clear();
        _notes.Clear();
        UpdatePreview();
    }

    private string BuildNotes()
    {
        string notes = _notes.Text.Trim();
        string source = $"KahnDispatcher {_settings.ActiveProfile}";
        return string.IsNullOrWhiteSpace(notes) ? source : $"{source} | {notes}";
    }

    private string BuildNotesOrDefault(string fallback)
    {
        string notes = _notes.Text.Trim();
        return string.IsNullOrWhiteSpace(notes) ? fallback : notes;
    }

    private void SetBusy(bool busy, string label)
    {
        _busy = busy;
        UseWaitCursor = busy;
        SetStatusText(label);
    }

    private void SetStatusText(string label)
    {
        _statusText = label;
        if (_statusLine is null)
            return;
        _statusLine.Text = $"status [{_settings.ActiveProfile}]: {label}";
    }

    private void ShowOutput(string label, string text)
    {
        _output.Text = $"{label}{Environment.NewLine}{text}";
        _output.SelectionStart = 0;
        _output.SelectionLength = 0;
    }

    private void UpdateRuntimeStateTile(string label, CommandResult result)
    {
        if (!TryParseJson(result.Output, out JsonDocument? document) || document is null)
        {
            if (result.ExitCode != 0)
                SetRuntimeStateTile("ERROR", Palette.Danger, Palette.Fore, result.DisplayText);
            return;
        }

        using (document)
        {
            JsonElement root = document.RootElement;
            if (TryGetBool(root, "ok", out bool ok) && !ok)
            {
                SetRuntimeStateTile("ERROR", Palette.Danger, Palette.Fore, Str(root, "error", "status read failed"));
                return;
            }

            if (label == "preflight")
                UpdateRuntimeStateTileFromPreflight(root);
            else
                UpdateRuntimeStateTileFromStatus(root);
        }
    }

    private void UpdateRuntimeStateTileFromStatus(JsonElement root)
    {
        string runtime = Str(root, "runtime_state", "-");
        string phase = Str(root, "phase", "-");
        string campaignStatus = Str(root, "campaign_status", "-");
        bool flat = true;
        string quantity = "0";
        if (root.TryGetProperty("position", out JsonElement position)
            && position.ValueKind == JsonValueKind.Object)
        {
            flat = PositionIsFlat(position);
            quantity = Str(position, "quantity", "0");
        }

        string details = $"runtime {runtime}, phase {phase}, campaign {campaignStatus}, flat {flat}, qty {quantity}";
        if (!string.Equals(runtime, "Running", StringComparison.OrdinalIgnoreCase))
        {
            SetRuntimeStateTile("STOPPED", Palette.Unknown, Palette.Fore, details);
            return;
        }
        if (!flat)
        {
            SetRuntimeStateTile("IN POS", Palette.Position, Palette.Fore, details);
            return;
        }
        if (HasAnyWarning(root))
        {
            SetRuntimeStateTile("STALE", Palette.Unsafe, Palette.Fore, details);
            return;
        }
        if (phase.Equals("Ready", StringComparison.OrdinalIgnoreCase))
        {
            SetRuntimeStateTile("READY", Palette.Ready, Palette.Fore, details);
            return;
        }
        if (phase.Equals("Retired", StringComparison.OrdinalIgnoreCase))
        {
            SetRuntimeStateTile("RETIRED", Palette.Retired, Palette.Fore, details);
            return;
        }

        SetRuntimeStateTile("ARMED", Palette.Armed, Palette.DarkText, details);
    }

    private void UpdateRuntimeStateTileFromPreflight(JsonElement root)
    {
        bool running = Bool(root, "runtime_running");
        bool fresh = Bool(root, "checkpoint_fresh");
        bool paths = Bool(root, "correct_paths");
        bool staleControl = Bool(root, "stale_control_file");
        string phase = Str(root, "phase", "-");
        bool flat = true;
        string quantity = "0";
        if (root.TryGetProperty("position", out JsonElement position)
            && position.ValueKind == JsonValueKind.Object)
        {
            flat = PositionIsFlat(position);
            quantity = Str(position, "quantity", "0");
        }

        string details = $"running {running}, fresh {fresh}, paths {paths}, phase {phase}, stale control {staleControl}, flat {flat}, qty {quantity}";
        if (!running)
        {
            SetRuntimeStateTile("STOPPED", Palette.Unknown, Palette.Fore, details);
            return;
        }
        if (!fresh)
        {
            SetRuntimeStateTile("STALE", Palette.Unsafe, Palette.Fore, details);
            return;
        }
        if (!paths)
        {
            SetRuntimeStateTile("PATHS", Palette.Danger, Palette.Fore, details);
            return;
        }
        if (!flat)
        {
            SetRuntimeStateTile("IN POS", Palette.Position, Palette.Fore, details);
            return;
        }
        if (staleControl)
        {
            SetRuntimeStateTile("CONTROL", Palette.Unsafe, Palette.Fore, details);
            return;
        }
        if (phase.Equals("Ready", StringComparison.OrdinalIgnoreCase))
        {
            SetRuntimeStateTile("READY", Palette.Ready, Palette.Fore, details);
            return;
        }
        if (phase.Equals("Retired", StringComparison.OrdinalIgnoreCase))
        {
            SetRuntimeStateTile("RETIRED", Palette.Retired, Palette.Fore, details);
            return;
        }

        SetRuntimeStateTile("ARMED", Palette.Armed, Palette.DarkText, details);
    }

    private void SetRuntimeStateTile(string text, Color backColor, Color foreColor, string details)
    {
        if (_runtimeStateTile is null)
            return;

        _runtimeStateTile.Text = text;
        _runtimeStateTile.BackColor = backColor;
        _runtimeStateTile.ForeColor = foreColor;
        _toolTip.SetToolTip(_runtimeStateTile, details);
    }

    private static bool IsPreflightUnsafeRejection(CommandResult result)
        => result.ExitCode != 0
            && result.DisplayText.Contains("preflight is not safe", StringComparison.OrdinalIgnoreCase);

    private static bool Confirm(string message, bool defaultYes)
        => MessageBox.Show(
            message,
            "Kahn Dispatcher",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning,
            defaultYes ? MessageBoxDefaultButton.Button1 : MessageBoxDefaultButton.Button2)
        == DialogResult.Yes;

    private static string OutputLabel(string label, int exitCode)
    {
        if (exitCode != 0)
        {
            return label switch
            {
                "validate" => "validation failed",
                "dispatch" => "dispatch rejected",
                "status" => "status failed",
                _ => $"{label} failed",
            };
        }

        return label switch
        {
            "validate" => "validated",
            "dispatch" => "dispatch result",
            "status" => "status",
            "cancel" => "cancel result",
            "flat" => "FLAT result",
            _ => label,
        };
    }

    private static ResolvedRange ParseRange(string text, string field)
    {
        string value = (text ?? string.Empty).Trim().Replace(':', '-');
        string[] parts = value.Split('-', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (parts.Length != 2)
            throw new InputException($"{field} range must be LOWER-HIGHER or LOWER:HIGHER");
        if (!double.TryParse(parts[0], NumberStyles.Float, CultureInfo.InvariantCulture, out double lower)
            || !double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out double upper)
            || !double.IsFinite(lower)
            || !double.IsFinite(upper)
            || lower <= 0
            || upper <= 0)
        {
            throw new InputException($"{field} range must contain finite positive prices");
        }
        if (lower > upper)
            (lower, upper) = (upper, lower);
        return new ResolvedRange(lower, upper);
    }

    private static ResolvedRange Envelope(ResolvedRange first, ResolvedRange second)
        => new(Math.Min(first.Lower, second.Lower), Math.Max(first.Upper, second.Upper));

    private static string FormatRangeArg(ResolvedRange range)
        => $"{FormatArg(range.Lower)}:{FormatArg(range.Upper)}";

    private static string FormatArg(double price)
        => price.ToString("0.########", CultureInfo.InvariantCulture);

    private static bool SamePath(string left, string right)
    {
        try
        {
            return Path.GetFullPath(Environment.ExpandEnvironmentVariables(left))
                .Equals(Path.GetFullPath(Environment.ExpandEnvironmentVariables(right)),
                    StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return string.Equals(left, right, StringComparison.OrdinalIgnoreCase);
        }
    }

    private static int ParseIntBox(TextBox box, string field, int min, int max)
    {
        string text = box.Text.Trim();
        if (!int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out int value)
            || value < min
            || value > max)
        {
            throw new InputException($"{field} must be a whole number from {min} to {max}");
        }
        return value;
    }

    private static int ReadIntOr(TextBox box, int fallback, int min, int max)
    {
        string text = box.Text.Trim();
        return int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out int value)
            && value >= min
            && value <= max
            ? value
            : Clamp(fallback, min, max);
    }

    private static int Clamp(int value, int min, int max)
        => Math.Max(min, Math.Min(max, value));

    private static string AbbrevPath(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || path.Length <= 54)
            return path;
        return "..." + path[^51..];
    }

    private static Label PlainLabel(string text, int width = 64)
        => new()
        {
            Text = text,
            Width = width,
            AutoSize = false,
            ForeColor = Palette.Muted,
            BackColor = Palette.Back,
            TextAlign = ContentAlignment.MiddleLeft,
            Margin = new Padding(0, 2, 8, 2),
        };

    private static void AddLabel(TableLayoutPanel panel, string text, int column, int row)
        => panel.Controls.Add(PlainLabel(text), column, row);

    private static TextBox Box(string text, int width = 150)
        => new()
        {
            Text = text,
            Width = width,
            BackColor = Palette.Input,
            ForeColor = Palette.Fore,
            BorderStyle = BorderStyle.FixedSingle,
            Margin = new Padding(0, 2, 8, 2),
        };

    private static RadioButton Radio(string text)
        => new()
        {
            Text = text,
            AutoSize = true,
            BackColor = Palette.Back,
            ForeColor = Palette.Fore,
            Margin = new Padding(0, 2, 10, 2),
        };

    private static FlowLayoutPanel RowPanel(params Control[] controls)
    {
        var panel = new FlowLayoutPanel
        {
            AutoSize = true,
            Dock = DockStyle.Fill,
            BackColor = Palette.Back,
            Margin = new Padding(0),
        };
        panel.Controls.AddRange(controls);
        return panel;
    }

    private static Button CommandButton(string text, EventHandler handler, bool danger = false)
    {
        var button = new Button
        {
            Text = text,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            MinimumSize = new Size(78, 28),
            FlatStyle = FlatStyle.Flat,
            BackColor = danger ? Palette.Danger : Palette.Button,
            ForeColor = Palette.Fore,
            Margin = new Padding(0, 0, 8, 0),
        };
        button.FlatAppearance.BorderColor = danger ? Palette.DangerBorder : Palette.ButtonBorder;
        button.Click += handler;
        return button;
    }

    private static bool TryParseJson(string text, out JsonDocument? document)
    {
        document = null;
        if (string.IsNullOrWhiteSpace(text))
            return false;
        try
        {
            document = JsonDocument.Parse(text);
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static bool TryGetObject(JsonElement element, string property, out JsonElement value)
    {
        value = default;
        return element.TryGetProperty(property, out value)
            && value.ValueKind == JsonValueKind.Object;
    }

    private static bool TryGetRange(JsonElement element, string property, out ResolvedRange range)
    {
        range = default;
        if (!TryGetObject(element, property, out JsonElement obj)
            || !TryGetFiniteDouble(obj, "lower", out double lower)
            || !TryGetFiniteDouble(obj, "upper", out double upper))
        {
            return false;
        }
        if (lower > upper)
            (lower, upper) = (upper, lower);
        range = new ResolvedRange(lower, upper);
        return true;
    }

    private static bool TryGetFiniteDouble(JsonElement element, string property, out double value)
    {
        value = 0;
        return element.TryGetProperty(property, out JsonElement item)
            && item.TryGetDouble(out value)
            && double.IsFinite(value);
    }

    private static bool TryGetString(JsonElement element, string property, out string value)
    {
        value = "";
        if (!element.TryGetProperty(property, out JsonElement item)
            || item.ValueKind != JsonValueKind.String)
        {
            return false;
        }
        value = item.GetString() ?? "";
        return true;
    }

    private static bool TryGetBool(JsonElement element, string property, out bool value)
    {
        value = false;
        if (!element.TryGetProperty(property, out JsonElement item)
            || item.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
        {
            return false;
        }
        value = item.GetBoolean();
        return true;
    }

    private static string Str(JsonElement element, string property, string fallback = "")
    {
        if (!element.TryGetProperty(property, out JsonElement item)
            || item.ValueKind == JsonValueKind.Null)
        {
            return fallback;
        }
        return item.ValueKind == JsonValueKind.String
            ? item.GetString() ?? fallback
            : item.ToString();
    }

    private static bool Bool(JsonElement element, string property)
        => element.TryGetProperty(property, out JsonElement item)
            && item.ValueKind == JsonValueKind.True;

    private static bool PositionIsFlat(JsonElement position)
    {
        bool flat = Bool(position, "flat");
        if (!flat
            && double.TryParse(Str(position, "quantity", "0"), NumberStyles.Float, CultureInfo.InvariantCulture, out double quantity))
        {
            flat = Math.Abs(quantity) < 0.000001;
        }
        return flat;
    }

    private static bool HasAnyWarning(JsonElement root)
        => root.TryGetProperty("warnings", out JsonElement warnings)
            && warnings.ValueKind == JsonValueKind.Array
            && warnings.GetArrayLength() > 0;

    private static string RawSuffix(string stderr)
        => string.IsNullOrWhiteSpace(stderr)
            ? ""
            : Environment.NewLine + Environment.NewLine + stderr.Trim();

    private sealed record KahnCommand(
        IReadOnlyList<string> Arguments,
        string Side,
        ResolvedRange Root,
        ResolvedRange Middle,
        ResolvedRange Harvest,
        ResolvedRange Arena,
        string Mode,
        int BaseQty,
        int ScaleQty,
        int OutgoingMax,
        int VisibleMax);

    private sealed record SketchImport(
        string Side,
        ResolvedRange Root,
        ResolvedRange Middle,
        ResolvedRange Harvest,
        string Signature);
}

internal readonly record struct ResolvedRange(double Lower, double Upper)
{
    public override string ToString()
        => $"{Lower.ToString("0.########", CultureInfo.InvariantCulture)}-{Upper.ToString("0.########", CultureInfo.InvariantCulture)}";
}

internal sealed class InputException : Exception
{
    public InputException(string message)
        : base(message)
    {
    }
}

internal sealed class KahnctlClient
{
    private readonly DispatcherSettings _settings;
    private readonly string _repoRoot;
    private readonly string _scriptPath;

    public KahnctlClient(DispatcherSettings settings)
    {
        _settings = settings;
        _repoRoot = FindRepoRoot();
        _scriptPath = Path.Combine(_repoRoot, "skills", "saavik", "scripts", "kahnctl.py");
    }

    public async Task<CommandResult> RunAsync(IReadOnlyList<string> args)
    {
        if (!File.Exists(_scriptPath))
        {
            return new CommandResult(
                -1,
                "",
                $"kahnctl.py not found at {_scriptPath}");
        }

        var start = new ProcessStartInfo
        {
            FileName = string.IsNullOrWhiteSpace(_settings.PythonExe) ? "python" : _settings.PythonExe,
            WorkingDirectory = _repoRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        start.ArgumentList.Add(_scriptPath);
        foreach (string arg in args)
            start.ArgumentList.Add(arg);

        try
        {
            using var process = new Process { StartInfo = start };
            process.Start();
            Task<string> stdout = process.StandardOutput.ReadToEndAsync();
            Task<string> stderr = process.StandardError.ReadToEndAsync();
            await process.WaitForExitAsync();
            return new CommandResult(process.ExitCode, await stdout, await stderr);
        }
        catch (Exception ex) when (ex is InvalidOperationException or IOException or System.ComponentModel.Win32Exception)
        {
            return new CommandResult(-1, "", ex.Message);
        }
    }

    private static string FindRepoRoot()
    {
        var candidates = new List<DirectoryInfo>();
        string? baseDir = AppContext.BaseDirectory;
        if (!string.IsNullOrWhiteSpace(baseDir))
            candidates.Add(new DirectoryInfo(baseDir));
        candidates.Add(new DirectoryInfo(Environment.CurrentDirectory));

        foreach (DirectoryInfo candidate in candidates)
        {
            DirectoryInfo? dir = candidate;
            while (dir != null)
            {
                if (File.Exists(Path.Combine(dir.FullName, "skills", "saavik", "scripts", "kahnctl.py")))
                    return dir.FullName;
                dir = dir.Parent;
            }
        }

        return Environment.CurrentDirectory;
    }
}

internal sealed record CommandResult(int ExitCode, string Output, string Error)
{
    public string DisplayText
        => string.IsNullOrWhiteSpace(Error)
            ? Output.Trim()
            : (Output.Trim() + Environment.NewLine + Error.Trim()).Trim();
}

internal sealed class DispatcherSettings
{
    public static readonly string DefaultRuntimeDir =
        Environment.ExpandEnvironmentVariables(@"%USERPROFILE%\Documents\KahnRuntime");

    private static readonly string SettingsDir =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "KahnDispatcher");

    private static readonly string SettingsPath = Path.Combine(SettingsDir, "settings.json");

    public string RuntimeDir { get; set; } = DefaultRuntimeDir;
    public string SketchDraftPath { get; set; } =
        Path.Combine(DefaultRuntimeDir, "saavik-probe.json");
    public string ActiveProfile { get; set; } = "ES";
    public List<RuntimeProfile> RuntimeProfiles { get; set; } = new();
    public string PythonExe { get; set; } = "python";
    public string Side { get; set; } = "long";
    public string ScaleMode { get; set; } = "scale_allowed";
    public string RootRange { get; set; } = "";
    public string MiddleRange { get; set; } = "";
    public string HarvestRange { get; set; } = "";
    public int BaseQuantity { get; set; } = 2;
    public int ScaleQuantity { get; set; } = 2;
    public int MaxQuantity { get; set; } = 10;
    public int MaxRetry { get; set; } = 3;
    public int TtlMinutes { get; set; } = 30;
    public bool RetireExistingIfFlat { get; set; } = true;
    public string Notes { get; set; } = "";

    public static DispatcherSettings Load()
    {
        try
        {
            if (!File.Exists(SettingsPath))
            {
                var defaults = new DispatcherSettings();
                defaults.NormalizeRuntimeProfiles();
                return defaults;
            }
            string text = File.ReadAllText(SettingsPath);
            var settings = JsonSerializer.Deserialize<DispatcherSettings>(text)
                ?? new DispatcherSettings();
            settings.NormalizeRuntimeProfiles();
            return settings;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            var settings = new DispatcherSettings();
            settings.NormalizeRuntimeProfiles();
            return settings;
        }
    }

    public void NormalizeRuntimeProfiles()
    {
        RuntimeProfiles ??= new List<RuntimeProfile>();
        var normalized = new List<RuntimeProfile>();
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (RuntimeProfile profile in RuntimeProfiles)
        {
            string name = (profile.Name ?? "").Trim();
            if (string.IsNullOrWhiteSpace(name) || !names.Add(name))
                continue;

            string runtimeDir = string.IsNullOrWhiteSpace(profile.RuntimeDir)
                ? RuntimeDir
                : profile.RuntimeDir;
            string sketchPath = string.IsNullOrWhiteSpace(profile.SketchDraftPath)
                ? Path.Combine(runtimeDir, "saavik-probe.json")
                : profile.SketchDraftPath;
            normalized.Add(new RuntimeProfile(name, runtimeDir, sketchPath));
        }

        AddProfileIfMissing(normalized, names, "DEFAULT", DefaultRuntimeDir);
        AddProfileIfMissing(normalized, names, "ES", Path.Combine(DefaultRuntimeDir, "ES"));
        AddProfileIfMissing(normalized, names, "NQ", Path.Combine(DefaultRuntimeDir, "NQ"));

        RuntimeProfiles = normalized;
        if (string.IsNullOrWhiteSpace(ActiveProfile)
            || RuntimeProfiles.All(profile => !profile.Name.Equals(ActiveProfile, StringComparison.OrdinalIgnoreCase)))
        {
            ActiveProfile = RuntimeProfiles.First(profile => profile.Name.Equals("ES", StringComparison.OrdinalIgnoreCase)).Name;
        }
        TrySelectRuntimeProfile(ActiveProfile);
    }

    public RuntimeProfile ActiveRuntimeProfile()
    {
        RuntimeProfile? profile = RuntimeProfiles.FirstOrDefault(
            item => item.Name.Equals(ActiveProfile, StringComparison.OrdinalIgnoreCase));
        return profile ?? RuntimeProfiles[0];
    }

    public bool TrySelectRuntimeProfile(string profileName)
    {
        RuntimeProfile? profile = RuntimeProfiles.FirstOrDefault(
            item => item.Name.Equals(profileName, StringComparison.OrdinalIgnoreCase));
        if (profile is null)
            return false;

        ActiveProfile = profile.Name;
        RuntimeDir = Environment.ExpandEnvironmentVariables(profile.RuntimeDir);
        SketchDraftPath = Environment.ExpandEnvironmentVariables(profile.SketchDraftPath);
        return true;
    }

    public void Save()
    {
        try
        {
            Directory.CreateDirectory(SettingsDir);
            var options = new JsonSerializerOptions
            {
                WriteIndented = true,
                DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            };
            File.WriteAllText(SettingsPath, JsonSerializer.Serialize(this, options));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
        }
    }

    private static void AddProfileIfMissing(
        List<RuntimeProfile> profiles,
        HashSet<string> names,
        string name,
        string runtimeDir)
    {
        if (!names.Add(name))
            return;
        profiles.Add(new RuntimeProfile(name, runtimeDir, Path.Combine(runtimeDir, "saavik-probe.json")));
    }
}

internal sealed class RuntimeProfile
{
    public RuntimeProfile()
    {
    }

    public RuntimeProfile(string name, string runtimeDir, string sketchDraftPath)
    {
        Name = name;
        RuntimeDir = runtimeDir;
        SketchDraftPath = sketchDraftPath;
    }

    public string Name { get; set; } = "";
    public string RuntimeDir { get; set; } = "";
    public string SketchDraftPath { get; set; } = "";
}

internal static class Palette
{
    public static readonly Color Back = Color.FromArgb(24, 24, 24);
    public static readonly Color Input = Color.FromArgb(35, 35, 35);
    public static readonly Color Output = Color.FromArgb(16, 16, 16);
    public static readonly Color Button = Color.FromArgb(48, 48, 48);
    public static readonly Color ButtonBorder = Color.FromArgb(82, 82, 82);
    public static readonly Color Danger = Color.FromArgb(92, 34, 34);
    public static readonly Color DangerBorder = Color.FromArgb(158, 64, 64);
    public static readonly Color Fore = Color.FromArgb(232, 232, 232);
    public static readonly Color Muted = Color.FromArgb(160, 160, 160);
    public static readonly Color Ready = Color.FromArgb(43, 130, 86);
    public static readonly Color Armed = Color.FromArgb(224, 178, 72);
    public static readonly Color Position = Color.FromArgb(168, 68, 58);
    public static readonly Color Retired = Color.FromArgb(65, 65, 65);
    public static readonly Color Unsafe = Color.FromArgb(116, 86, 42);
    public static readonly Color Unknown = Color.FromArgb(50, 50, 50);
    public static readonly Color DarkText = Color.FromArgb(18, 18, 18);
}
