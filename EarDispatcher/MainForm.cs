using System.Diagnostics;
using System.Diagnostics.CodeAnalysis;
using System.Drawing;
using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace EarDispatcher;

internal sealed class MainForm : Form
{
    private readonly DispatcherSettings _settings;
    private readonly EarctlClient _earctl;

    private RadioButton _longSide = null!;
    private RadioButton _shortSide = null!;
    private TextBox _priceBase = null!;
    private TextBox _contextRange = null!;
    private TextBox _orderRange = null!;
    private TextBox _targetPrice = null!;
    private TextBox _targetReference = null!;
    private TextBox _invalidationPrice = null!;
    private CheckBox _autoOrder = null!;
    private CheckBox _campaign = null!;
    private NumericUpDown _timeoutMinutes = null!;
    private TextBox _baseQuantity = null!;
    private TextBox _addQuantity = null!;
    private TextBox _maxPosition = null!;
    private CheckBox _useRuntimeMax = null!;
    private TextBox _tag = null!;
    private TextBox _notes = null!;
    private Label _contextPreview = null!;
    private Label _orderPreview = null!;
    private Label _targetPreview = null!;
    private Label _invalidationPreview = null!;
    private Label _statusLine = null!;
    private TextBox _output = null!;
    private ToolStripMenuItem _topMostMenu = null!;
    private ToolStripMenuItem _rawJsonMenu = null!;

    private bool _busy;
    private bool _updatingOrder;
    private string _statusText = "idle";
    private int? _runtimeMaxPosition;
    private System.Windows.Forms.Timer? _sketchPollTimer;
    private DateTime _lastSketchWriteUtc = DateTime.MinValue;
    private string _lastSketchSignature = "";

    public MainForm()
    {
        _settings = DispatcherSettings.Load();
        _earctl = new EarctlClient(_settings);
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
        _sketchPollTimer?.Stop();
        _sketchPollTimer?.Dispose();
        SaveSettings();
        base.OnFormClosing(e);
    }

    private void BuildUi()
    {
        Text = "EAR Dispatcher";
        Icon = AppIcon.Create();
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(650, 520);
        ClientSize = new Size(700, 580);
        KeyPreview = true;
        AutoScaleMode = AutoScaleMode.Dpi;
        Font = new Font("Cascadia Mono", 9.0f, FontStyle.Regular, GraphicsUnit.Point);
        BackColor = Palette.Back;
        ForeColor = Palette.Fore;
        TopMost = _settings.AlwaysOnTop;

        var main = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 6,
            Padding = new Padding(10),
            BackColor = Palette.Back,
        };
        main.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        main.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        main.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        main.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        main.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        main.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        Controls.Add(main);

        ContextMenuStrip menu = BuildContextMenu();
        ContextMenuStrip = menu;
        main.ContextMenuStrip = menu;

        var header = new Label
        {
            Text = "EAR Dispatcher",
            AutoSize = true,
            Font = new Font(Font, FontStyle.Bold),
            Margin = new Padding(0, 0, 0, 8),
        };
        main.Controls.Add(header, 0, 0);

        var form = new TableLayoutPanel
        {
            Dock = DockStyle.Top,
            ColumnCount = 5,
            RowCount = 8,
            AutoSize = true,
            BackColor = Palette.Back,
        };
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 72));
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 148));
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 34));
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
        main.Controls.Add(form, 0, 1);

        _longSide = new RadioButton
        {
            Text = "LONG",
            AutoSize = true,
            ForeColor = Palette.Fore,
            BackColor = Palette.Back,
        };
        _shortSide = new RadioButton
        {
            Text = "SHORT",
            AutoSize = true,
            ForeColor = Palette.Fore,
            BackColor = Palette.Back,
        };
        var sidePanel = RowPanel(_longSide, _shortSide);
        AddLabel(form, "Side", 0, 0);
        form.Controls.Add(sidePanel, 1, 0);

        _priceBase = Box("30000");
        AddLabel(form, "Base", 2, 0);
        form.Controls.Add(_priceBase, 3, 0);

        _orderRange = Box("205-218.5");
        _orderPreview = PreviewLabel();
        AddLabel(form, "Order", 0, 1);
        form.Controls.Add(_orderRange, 1, 1);
        AddLabel(form, "=>", 2, 1);
        form.Controls.Add(_orderPreview, 3, 1);

        _contextRange = Box("180-235");
        _contextPreview = PreviewLabel();
        _autoOrder = new CheckBox
        {
            Text = "auto ctx",
            Checked = true,
            AutoSize = true,
            ForeColor = Palette.Fore,
            BackColor = Palette.Back,
            Margin = new Padding(0, 4, 12, 0),
        };
        _campaign = new CheckBox
        {
            Text = "cam",
            Checked = true,
            AutoSize = true,
            ForeColor = Palette.Fore,
            BackColor = Palette.Back,
            Margin = new Padding(0, 4, 0, 0),
        };
        AddLabel(form, "Context", 0, 2);
        form.Controls.Add(_contextRange, 1, 2);
        AddLabel(form, "=>", 2, 2);
        form.Controls.Add(_contextPreview, 3, 2);
        form.Controls.Add(RowPanel(_autoOrder, _campaign), 4, 2);

        _targetPrice = Box("");
        _targetReference = Box("");
        _targetReference.Width = 116;
        _targetReference.PlaceholderText = "ref";
        _targetPreview = PreviewLabel();
        AddLabel(form, "TP", 0, 3);
        form.Controls.Add(_targetPrice, 1, 3);
        AddLabel(form, "=>", 2, 3);
        form.Controls.Add(_targetPreview, 3, 3);
        form.Controls.Add(_targetReference, 4, 3);

        _invalidationPrice = Box("");
        _invalidationPreview = PreviewLabel();
        AddLabel(form, "Abort", 0, 4);
        form.Controls.Add(_invalidationPrice, 1, 4);
        AddLabel(form, "=>", 2, 4);
        form.Controls.Add(_invalidationPreview, 3, 4);

        _baseQuantity = Box("2");
        _baseQuantity.Width = 42;
        _addQuantity = Box("1");
        _addQuantity.Width = 42;
        _maxPosition = Box("5");
        _maxPosition.Width = 42;
        _timeoutMinutes = new NumericUpDown
        {
            Minimum = 1,
            Maximum = 480,
            Value = 30,
            Increment = 5,
            Width = 54,
            BackColor = Palette.Input,
            ForeColor = Palette.Fore,
            BorderStyle = BorderStyle.FixedSingle,
            Margin = new Padding(0, 2, 8, 2),
        };
        _useRuntimeMax = new CheckBox
        {
            Text = "EAR",
            Checked = true,
            AutoSize = true,
            ForeColor = Palette.Fore,
            BackColor = Palette.Back,
            Margin = new Padding(0, 4, 0, 0),
        };
        AddLabel(form, "Qty", 0, 5);
        var qtyPanel = RowPanel(
            PlainLabel("base", 38), _baseQuantity,
            PlainLabel("add", 30), _addQuantity,
            PlainLabel("max", 30), _maxPosition,
            _useRuntimeMax,
            PlainLabel("ttl", 28), _timeoutMinutes,
            PlainLabel("m", 18));
        form.SetColumnSpan(qtyPanel, 4);
        form.Controls.Add(qtyPanel, 1, 5);

        _tag = Box("");
        AddLabel(form, "Tag", 0, 6);
        form.SetColumnSpan(_tag, 4);
        form.Controls.Add(_tag, 1, 6);

        _notes = Box("");
        _notes.Multiline = true;
        _notes.Height = 54;
        AddLabel(form, "Notes", 0, 7);
        form.SetColumnSpan(_notes, 4);
        form.Controls.Add(_notes, 1, 7);

        var directiveButtons = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            BackColor = Palette.Back,
            Margin = new Padding(0, 10, 0, 3),
        };
        main.Controls.Add(directiveButtons, 0, 2);
        directiveButtons.Controls.Add(CommandButton("F9 Status", async (_, _) => await RunStatusAsync()));
        directiveButtons.Controls.Add(CommandButton("F5 Validate", async (_, _) => await RunDispatchAsync(dryRun: true)));
        directiveButtons.Controls.Add(CommandButton("Ctrl+Enter Dispatch", async (_, _) => await RunDispatchAsync(dryRun: false)));
        directiveButtons.Controls.Add(CommandButton("Esc Clear", (_, _) => ClearEntryFields()));

        var earButtons = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            BackColor = Palette.Back,
            Margin = new Padding(0, 0, 0, 8),
        };
        main.Controls.Add(earButtons, 0, 3);
        earButtons.Controls.Add(CommandButton("Reissue", async (_, _) => await RunReissueAsync(continueLineage: false)));
        earButtons.Controls.Add(CommandButton("Continue", async (_, _) => await RunReissueAsync(continueLineage: true)));
        earButtons.Controls.Add(CommandButton("Ctrl+Del Cancel", async (_, _) => await RunCancelActiveAsync()));
        earButtons.Controls.Add(CommandButton("FLAT", async (_, _) => await RunFlatAsync(), danger: true));

        _statusLine = new Label
        {
            Dock = DockStyle.Top,
            Text = _settings.AlwaysOnTop ? "status [top]: idle" : "status: idle",
            AutoSize = true,
            ForeColor = Palette.Muted,
            BackColor = Palette.Back,
            Margin = new Padding(0, 0, 0, 4),
        };
        main.Controls.Add(_statusLine, 0, 4);

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
            ContextMenuStrip = menu,
        };
        main.Controls.Add(_output, 0, 5);
        ApplyContextMenu(main, menu);
        _output.ContextMenuStrip = menu;
    }

    private static void ApplyContextMenu(Control root, ContextMenuStrip menu)
    {
        foreach (Control child in root.Controls)
        {
            if (child is not TextBox and not NumericUpDown)
                child.ContextMenuStrip = menu;
            ApplyContextMenu(child, menu);
        }
    }

    private ContextMenuStrip BuildContextMenu()
    {
        var menu = new ContextMenuStrip
        {
            BackColor = Palette.Input,
            ForeColor = Palette.Fore,
        };

        _topMostMenu = new ToolStripMenuItem("Always on top")
        {
            Checked = _settings.AlwaysOnTop,
            CheckOnClick = true,
        };
        _topMostMenu.CheckedChanged += (_, _) =>
        {
            TopMost = _topMostMenu.Checked;
            _settings.AlwaysOnTop = _topMostMenu.Checked;
            SetStatusText(_statusText);
        };

        _rawJsonMenu = new ToolStripMenuItem("Show raw JSON")
        {
            Checked = _settings.ShowRawJson,
            CheckOnClick = true,
        };
        _rawJsonMenu.CheckedChanged += (_, _) =>
        {
            _settings.ShowRawJson = _rawJsonMenu.Checked;
        };

        var copyOutput = new ToolStripMenuItem("Copy output");
        copyOutput.Click += (_, _) =>
        {
            if (_output.TextLength > 0)
                Clipboard.SetText(_output.Text);
        };

        menu.Items.Add(_topMostMenu);
        menu.Items.Add(_rawJsonMenu);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add(copyOutput);
        return menu;
    }

    private void WireEvents()
    {
        _priceBase.TextChanged += (_, _) => OnAutoOrderSourceChanged();
        _contextRange.TextChanged += (_, _) => OnContextRangeChanged();
        _orderRange.TextChanged += (_, _) => OnAutoOrderSourceChanged();
        _targetPrice.TextChanged += (_, _) => OnAutoOrderSourceChanged();
        _invalidationPrice.TextChanged += (_, _) => UpdatePreviews();
        _longSide.CheckedChanged += (_, _) => OnAutoOrderSourceChanged();
        _shortSide.CheckedChanged += (_, _) => OnAutoOrderSourceChanged();
        _autoOrder.CheckedChanged += (_, _) =>
        {
            if (_autoOrder.Checked)
                ApplyAutoOrder();
            UpdatePreviews();
        };
        _campaign.CheckedChanged += (_, _) =>
        {
            UpdateCampaignState();
            OnAutoOrderSourceChanged();
        };
        _useRuntimeMax.CheckedChanged += (_, _) => UpdateMaxState();
        KeyDown += MainForm_KeyDown;
        UpdateCampaignState();
        UpdateMaxState();
        ApplyAutoOrder();
        UpdatePreviews();
    }

    private async void MainForm_KeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Control && e.KeyCode == Keys.Enter)
        {
            e.SuppressKeyPress = true;
            await RunDispatchAsync(dryRun: false);
        }
        else if (e.Control && e.KeyCode == Keys.Delete)
        {
            e.SuppressKeyPress = true;
            await RunCancelActiveAsync();
        }
        else if (e.KeyCode == Keys.F5)
        {
            e.SuppressKeyPress = true;
            await RunDispatchAsync(dryRun: true);
        }
        else if (e.KeyCode == Keys.F9)
        {
            e.SuppressKeyPress = true;
            await RunStatusAsync();
        }
        else if (e.KeyCode == Keys.Escape)
        {
            e.SuppressKeyPress = true;
            ClearEntryFields();
        }
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (keyData == Keys.Enter && ActiveControl is Button)
        {
            ActiveControl = _output;
            return true;
        }

        return base.ProcessCmdKey(ref msg, keyData);
    }

    private async Task RunStatusAsync(bool silent = false)
    {
        if (_busy)
            return;

        await RunCommandAsync(
            "status",
            new[] { "--runtime-dir", _settings.RuntimeDir, "status", "--recent-events", "8" },
            result =>
            {
                if (TryParseJson(result.Output, out JsonDocument? document))
                {
                    using (document)
                    {
                        ApplyRuntimeMax(document.RootElement);
                        return WithRaw(FormatStatus(document.RootElement), document.RootElement);
                    }
                }

                return result.DisplayText;
            },
            silent);
    }

    private async Task RunDispatchAsync(bool dryRun)
    {
        if (_busy)
            return;

        DispatchCommand command;
        try
        {
            command = BuildDispatchCommand(dryRun);
        }
        catch (InputException ex)
        {
            ShowOutput("input invalid", ex.Message);
            return;
        }

        if (!dryRun)
        {
            SetBusy(true, "preflight");
            CommandResult status;
            try
            {
                status = await _earctl.RunAsync(
                    new[] { "--runtime-dir", _settings.RuntimeDir, "status", "--recent-events", "8" });
            }
            finally
            {
                SetBusy(false, "idle");
            }

            if (TryParseJson(status.Output, out JsonDocument? statusDoc))
            {
                using (statusDoc)
                {
                    ApplyRuntimeMax(statusDoc.RootElement);
                    string blockers = FormatBlockers(statusDoc.RootElement);
                    if (!string.IsNullOrWhiteSpace(blockers))
                    {
                        ShowOutput("dispatch blocked", WithRaw(blockers, statusDoc.RootElement));
                        return;
                    }

                    string priceScale = FormatPriceScaleGuard(statusDoc.RootElement, command.Prices);
                    if (!string.IsNullOrWhiteSpace(priceScale))
                    {
                        ShowOutput("dispatch blocked", WithRaw(priceScale, statusDoc.RootElement));
                        return;
                    }
                }
            }
            else if (status.ExitCode != 0)
            {
                ShowOutput("status failed", status.DisplayText);
                return;
            }
        }

        await RunCommandAsync(
            dryRun ? "validate" : "dispatch",
            command.Arguments,
            result =>
            {
                JsonDocument? document = null;
                try
                {
                    string json = !string.IsNullOrWhiteSpace(result.Output)
                        ? result.Output
                        : result.Error;
                    if (TryParseJson(json, out document))
                        return WithRaw(FormatDispatchResult(document.RootElement, dryRun), document.RootElement);
                    return result.DisplayText;
                }
                finally
                {
                    document?.Dispose();
                }
            });
    }

    private async Task RunReissueAsync(bool continueLineage)
    {
        if (_busy)
            return;

        SetBusy(true, "preflight");
        CommandResult status;
        try
        {
            status = await _earctl.RunAsync(
                new[] { "--runtime-dir", _settings.RuntimeDir, "status", "--recent-events", "8" });
        }
        finally
        {
            SetBusy(false, "idle");
        }

        string confirmText = $"{(continueLineage ? "CONTINUE" : "REISSUE")} last accepted directive?";
        if (TryParseJson(status.Output, out JsonDocument? statusDoc))
        {
            using (statusDoc)
            {
                ApplyRuntimeMax(statusDoc.RootElement);
                string priceScale = FormatLastAcceptedPriceScaleGuard(statusDoc.RootElement);
                if (!string.IsNullOrWhiteSpace(priceScale))
                {
                    ShowOutput("reissue blocked", WithRaw(priceScale, statusDoc.RootElement));
                    return;
                }

                string summary = FormatLastAcceptedDirectiveSummary(statusDoc.RootElement);
                if (!string.IsNullOrWhiteSpace(summary))
                    confirmText += Environment.NewLine + Environment.NewLine + summary;
            }
        }
        else if (status.ExitCode != 0)
        {
            ShowOutput("status failed", status.DisplayText);
            return;
        }

        if (!Confirm(confirmText))
            return;

        var args = new List<string>
        {
            "--runtime-dir", _settings.RuntimeDir,
            "reissue-last-accepted",
            "--ttl-minutes", ((int)_timeoutMinutes.Value).ToString(CultureInfo.InvariantCulture),
        };
        string reason = BuildNotes();
        if (!string.IsNullOrWhiteSpace(reason))
            args.AddRange(new[] { "--reason", reason });
        if (continueLineage)
            args.Add("--continue-lineage");

        await RunCommandAsync(
            continueLineage ? "continue" : "reissue",
            args,
            result => FormatJsonCommandResult(result, "directive_id"));
    }

    private async Task RunCancelActiveAsync()
    {
        if (_busy)
            return;

        if (!Confirm("Cancel active directive? EAR may flatten directive-owned position.", defaultYes: true))
            return;

        var args = new List<string>
        {
            "--runtime-dir", _settings.RuntimeDir,
            "cancel-active",
            "--reason", BuildNotesOrDefault("Dispatcher cancel"),
        };
        await RunCommandAsync("cancel", args, result => FormatJsonCommandResult(result, "command_id"));
    }

    private async Task RunFlatAsync()
    {
        if (_busy)
            return;

        if (!Confirm("Issue FLAT for the bound EAR account/symbol?"))
            return;

        var args = new List<string>
        {
            "--runtime-dir", _settings.RuntimeDir,
            "control",
            "--action", "FLAT",
            "--reason", BuildNotesOrDefault("Dispatcher FLAT"),
        };
        await RunCommandAsync("flat", args, result => FormatJsonCommandResult(result, "command_id"));
    }

    private async Task RunCommandAsync(
        string label,
        IReadOnlyList<string> args,
        Func<CommandResult, string> formatter,
        bool silent = false)
    {
        SetBusy(true, label);
        CommandResult result;
        try
        {
            result = await _earctl.RunAsync(args);
        }
        finally
        {
            SetBusy(false, "idle");
        }

        string text = formatter(result);
        if (!silent || result.ExitCode != 0)
            ShowOutput(OutputLabel(label, result.ExitCode), text);
    }

    private DispatchCommand BuildDispatchCommand(bool dryRun)
    {
        double basePrice = ParsePriceBase();
        ResolvedRange order = PriceInput.ParseRange(_orderRange.Text, basePrice, "order");
        double target = PriceInput.ParsePrice(_targetPrice.Text, basePrice, "target");

        int baseQty = ParsePositiveInt(_baseQuantity.Text, "base quantity");
        bool campaign = _campaign.Checked;
        int addQty = campaign ? ParsePositiveInt(_addQuantity.Text, "add quantity") : 0;
        int maxPosition = campaign ? ParseMaxPosition() : baseQty;
        if (campaign && baseQty + addQty > maxPosition)
            throw new InputException("campaign requires base quantity + add quantity <= max position");

        string side = _longSide.Checked ? "long" : "short";
        ResolvedRange? addRange = null;
        if (campaign)
            addRange = CampaignRange(order, target, side);

        ResolvedRange context = order;
        if (_autoOrder.Checked)
        {
            if (addRange.HasValue)
                context = Envelope(context, addRange.Value);
        }
        else
        {
            ResolvedRange userContext = PriceInput.ParseRange(_contextRange.Text, basePrice, "context");
            context = Envelope(userContext, order);
            if (addRange.HasValue)
                context = Envelope(context, addRange.Value);
        }

        var priceScaleValues = new List<double>
        {
            order.Lower,
            order.Upper,
            context.Lower,
            context.Upper,
            target,
        };
        if (addRange.HasValue)
        {
            priceScaleValues.Add(addRange.Value.Lower);
            priceScaleValues.Add(addRange.Value.Upper);
        }

        var args = new List<string>
        {
            "--runtime-dir", _settings.RuntimeDir,
            "dispatch",
            "--side", side,
            "--order-range", FormatArg(order.Lower), FormatArg(order.Upper),
            "--context-range", FormatArg(context.Lower), FormatArg(context.Upper),
            "--base-quantity", baseQty.ToString(CultureInfo.InvariantCulture),
            "--add-quantity", addQty.ToString(CultureInfo.InvariantCulture),
            "--max-position", maxPosition.ToString(CultureInfo.InvariantCulture),
            "--target-price", FormatArg(target),
            "--ttl-minutes", ((int)_timeoutMinutes.Value).ToString(CultureInfo.InvariantCulture),
            "--wait-seconds", "3",
        };

        if (campaign)
        {
            args.AddRange(new[] { "--add-range", FormatArg(addRange!.Value.Lower), FormatArg(addRange.Value.Upper) });
        }
        else
        {
            args.Add("--no-adds");
        }

        string invalidationText = _invalidationPrice.Text.Trim();
        if (invalidationText.Length > 0)
        {
            double invalidation = PriceInput.ParsePrice(invalidationText, basePrice, "invalidation");
            args.AddRange(new[] { "--pre-entry-invalidation", FormatArg(invalidation) });
            priceScaleValues.Add(invalidation);
        }

        string targetReference = _targetReference.Text.Trim();
        if (targetReference.Length > 0)
            args.AddRange(new[] { "--target-reference", targetReference });

        string notes = BuildNotes();
        if (notes.Length > 0)
            args.AddRange(new[] { "--notes", notes });

        if (dryRun)
            args.Add("--dry-run");

        return new DispatchCommand(args, priceScaleValues);
    }

    private void OnAutoOrderSourceChanged()
    {
        if (_autoOrder.Checked)
            ApplyAutoOrder();
        UpdatePreviews();
    }

    private void OnContextRangeChanged()
    {
        if (!_updatingOrder && _autoOrder.Checked)
            _autoOrder.Checked = false;
        UpdatePreviews();
    }

    private void ApplyAutoOrder()
    {
        try
        {
            string text = BuildAutoOrderText();
            if (text.Length == 0)
                return;

            _updatingOrder = true;
            _contextRange.Text = text;
        }
        catch (InputException)
        {
            // Leave the manually visible field untouched until order and TP are parseable.
        }
        finally
        {
            _updatingOrder = false;
        }
    }

    private string BuildAutoOrderText()
    {
        double basePrice = ParsePriceBase();
        ResolvedRange order = PriceInput.ParseRange(_orderRange.Text, basePrice, "order");
        if (!_campaign.Checked)
            return $"{FormatInputPrice(order.Lower, basePrice)}-{FormatInputPrice(order.Upper, basePrice)}";

        double target = PriceInput.ParsePrice(_targetPrice.Text, basePrice, "target");
        string side = _longSide.Checked ? "long" : "short";
        ResolvedRange campaign = CampaignRange(order, target, side);
        ResolvedRange context = Envelope(order, campaign);
        return $"{FormatInputPrice(context.Lower, basePrice)}-{FormatInputPrice(context.Upper, basePrice)}";
    }

    private void UpdatePreviews()
    {
        if (!double.TryParse(_priceBase.Text.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out double basePrice)
            || basePrice <= 0)
        {
            _contextPreview.Text = "base?";
            _orderPreview.Text = "base?";
            _targetPreview.Text = "base?";
            _invalidationPreview.Text = "base?";
            return;
        }

        _contextPreview.Text = PreviewRange(_contextRange.Text, basePrice, "context");
        _orderPreview.Text = PreviewRange(_orderRange.Text, basePrice, "order");
        _targetPreview.Text = PreviewPrice(_targetPrice.Text, basePrice, "target");
        _invalidationPreview.Text = PreviewPrice(_invalidationPrice.Text, basePrice, "invalidation");
    }

    private static string PreviewRange(string text, double basePrice, string name)
    {
        if (string.IsNullOrWhiteSpace(text))
            return "";
        try
        {
            ResolvedRange range = PriceInput.ParseRange(text, basePrice, name);
            return $"{FormatDisplay(range.Lower)} - {FormatDisplay(range.Upper)}";
        }
        catch (InputException ex)
        {
            return ex.Message;
        }
    }

    private static string PreviewPrice(string text, double basePrice, string name)
    {
        if (string.IsNullOrWhiteSpace(text))
            return "";
        try
        {
            double price = PriceInput.ParsePrice(text, basePrice, name);
            return FormatDisplay(price);
        }
        catch (InputException ex)
        {
            return ex.Message;
        }
    }

    private void UpdateCampaignState()
    {
        _addQuantity.Enabled = _campaign.Checked;
        _useRuntimeMax.Enabled = _campaign.Checked;
        _maxPosition.Enabled = _campaign.Checked && !_useRuntimeMax.Checked;
    }

    private void UpdateMaxState()
    {
        if (_useRuntimeMax.Checked && _runtimeMaxPosition.HasValue)
            _maxPosition.Text = _runtimeMaxPosition.Value.ToString(CultureInfo.InvariantCulture);
        _maxPosition.Enabled = _campaign.Checked && !_useRuntimeMax.Checked;
    }

    private void ApplyRuntimeMax(JsonElement root)
    {
        if (root.TryGetProperty("runtime", out JsonElement runtime)
            && TryInt(runtime, "instance_max_quantity", out int max))
        {
            _runtimeMaxPosition = max;
            if (_useRuntimeMax.Checked)
                _maxPosition.Text = max.ToString(CultureInfo.InvariantCulture);
        }
    }

    private double ParsePriceBase()
    {
        if (!double.TryParse(_priceBase.Text.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out double value)
            || value <= 0)
        {
            throw new InputException("base must be a positive number");
        }

        return value;
    }

    private int ParseMaxPosition()
    {
        if (_useRuntimeMax.Checked && _runtimeMaxPosition.HasValue)
            return _runtimeMaxPosition.Value;
        return ParsePositiveInt(_maxPosition.Text, "max position");
    }

    private static int ParsePositiveInt(string text, string name)
    {
        if (!int.TryParse(text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out int value)
            || value < 1)
        {
            throw new InputException($"{name} must be a positive integer");
        }

        return value;
    }

    private string BuildNotes()
    {
        var parts = new List<string>();
        string tag = _tag.Text.Trim();
        string notes = _notes.Text.Trim();
        if (tag.Length > 0)
            parts.Add($"tag={tag}");
        if (notes.Length > 0)
            parts.Add(notes);
        return string.Join(" | ", parts);
    }

    private string BuildNotesOrDefault(string fallback)
    {
        string notes = BuildNotes();
        return string.IsNullOrWhiteSpace(notes) ? fallback : notes;
    }

    private void ApplySettings()
    {
        _priceBase.Text = _settings.PriceBase;
        _contextRange.Text = _settings.ContextRange;
        _orderRange.Text = _settings.OrderRange;
        _targetPrice.Text = _settings.TargetPrice;
        _targetReference.Text = _settings.TargetReference;
        _invalidationPrice.Text = _settings.InvalidationPrice;
        _campaign.Checked = _settings.CampaignEnabled;
        _autoOrder.Checked = _settings.AutoOrder;
        _timeoutMinutes.Value = Math.Clamp(_settings.TimeoutMinutes, 1, 480);
        _baseQuantity.Text = _settings.BaseQuantity;
        _addQuantity.Text = _settings.AddQuantity;
        _maxPosition.Text = _settings.MaxPosition;
        _useRuntimeMax.Checked = _settings.UseRuntimeMax;
        _tag.Text = _settings.Tag;
        _notes.Text = _settings.Notes;
        if (_settings.Side.Equals("short", StringComparison.OrdinalIgnoreCase))
            _shortSide.Checked = true;
        else
            _longSide.Checked = true;
    }

    private void SaveSettings()
    {
        _settings.Side = _longSide.Checked ? "long" : "short";
        _settings.PriceBase = _priceBase.Text;
        _settings.ContextRange = _contextRange.Text;
        _settings.OrderRange = _orderRange.Text;
        _settings.TargetPrice = _targetPrice.Text;
        _settings.TargetReference = _targetReference.Text;
        _settings.InvalidationPrice = _invalidationPrice.Text;
        _settings.CampaignEnabled = _campaign.Checked;
        _settings.AutoOrder = _autoOrder.Checked;
        _settings.TimeoutMinutes = (int)_timeoutMinutes.Value;
        _settings.BaseQuantity = _baseQuantity.Text;
        _settings.AddQuantity = _addQuantity.Text;
        _settings.MaxPosition = _maxPosition.Text;
        _settings.UseRuntimeMax = _useRuntimeMax.Checked;
        _settings.AlwaysOnTop = TopMost;
        _settings.ShowRawJson = _rawJsonMenu.Checked;
        _settings.Tag = _tag.Text;
        _settings.Notes = _notes.Text;
        _settings.Save();
    }

    private void ClearEntryFields()
    {
        _contextRange.Clear();
        _orderRange.Clear();
        _targetPrice.Clear();
        _targetReference.Clear();
        _invalidationPrice.Clear();
        _tag.Clear();
        _notes.Clear();
        UpdatePreviews();
    }

    private void SetBusy(bool busy, string label)
    {
        _busy = busy;
        UseWaitCursor = busy;
        SetStatusText(label);
    }

    private void ShowOutput(string label, string text)
    {
        SetStatusText(label);
        _output.Text = text.Replace("\n", Environment.NewLine);
        _output.SelectionStart = 0;
        _output.SelectionLength = 0;
    }

    private void SetStatusText(string label)
    {
        _statusText = label;
        _statusLine.Text = TopMost ? $"status [top]: {label}" : $"status: {label}";
    }

    private void StartSketchDraftImport()
    {
        if (string.IsNullOrWhiteSpace(_settings.SketchDraftPath)
            && string.IsNullOrWhiteSpace(_settings.RuntimeDir))
        {
            return;
        }

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
            // A bad or unavailable probe path should not affect manual dispatch.
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
        try
        {
            writeUtc = File.GetLastWriteTimeUtc(path);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return;
        }

        if (writeUtc <= _lastSketchWriteUtc)
            return;

        string text;
        try
        {
            text = File.ReadAllText(path);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return;
        }

        _lastSketchWriteUtc = writeUtc;
        if (!TryParseSketchImport(text, out SketchImport? import) || import == null)
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
            configured = Path.Combine(_settings.RuntimeDir, "directive-sketch-probe.json");

        string expanded = Environment.ExpandEnvironmentVariables(configured);
        return string.IsNullOrWhiteSpace(expanded) ? "" : Path.GetFullPath(expanded);
    }

    private void ApplySketchImport(SketchImport import)
    {
        if (import.Side == "short")
            _shortSide.Checked = true;
        else
            _longSide.Checked = true;

        _orderRange.Text = $"{FormatArg(import.OrderLower)}-{FormatArg(import.OrderUpper)}";
        _targetPrice.Text = FormatArg(import.TargetPrice);

        if (!_autoOrder.Checked)
            _autoOrder.Checked = true;
        else
            ApplyAutoOrder();

        UpdatePreviews();
        SetStatusText(
            $"sketch {import.Side.ToUpperInvariant()} {FormatDisplay(import.OrderLower)}-{FormatDisplay(import.OrderUpper)} tp {FormatDisplay(import.TargetPrice)}");
    }

    private static bool TryParseSketchImport(string text, [NotNullWhen(true)] out SketchImport? import)
    {
        import = null;
        try
        {
            using JsonDocument document = JsonDocument.Parse(text);
            JsonElement root = document.RootElement;
            if (!TryGetString(root, "status", out string? status))
                return false;
            if (!status.Equals("ok", StringComparison.OrdinalIgnoreCase))
                return false;

            if (!TryGetObject(root, "active_draft", out JsonElement draft))
                return false;
            if (!TryGetString(draft, "side", out string? side))
                return false;

            side = side.Trim().ToLowerInvariant();
            if (side is not ("long" or "short"))
                return false;

            if (!TryGetObject(draft, "order_context_range", out JsonElement range)
                || !TryGetFiniteDouble(range, "lower", out double lower)
                || !TryGetFiniteDouble(range, "upper", out double upper)
                || !TryGetFiniteDouble(draft, "target_price", out double target))
            {
                return false;
            }

            if (lower > upper)
                (lower, upper) = (upper, lower);
            if (side == "long" && target <= upper)
                return false;
            if (side == "short" && target >= lower)
                return false;

            string generatedAt = TryGetString(root, "generated_at_utc", out string? value) ? value : "";
            string signature = string.Join("|",
                generatedAt,
                side,
                lower.ToString("R", CultureInfo.InvariantCulture),
                upper.ToString("R", CultureInfo.InvariantCulture),
                target.ToString("R", CultureInfo.InvariantCulture));
            import = new SketchImport(side, lower, upper, target, signature);
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static bool TryGetObject(JsonElement parent, string propertyName, out JsonElement value)
        => parent.TryGetProperty(propertyName, out value) && value.ValueKind == JsonValueKind.Object;

    private static bool TryGetString(JsonElement parent, string propertyName, [NotNullWhen(true)] out string? value)
    {
        value = null;
        if (!parent.TryGetProperty(propertyName, out JsonElement element))
            return false;

        value = element.ValueKind == JsonValueKind.String ? element.GetString() : element.ToString();
        return !string.IsNullOrWhiteSpace(value);
    }

    private static bool TryGetFiniteDouble(JsonElement parent, string propertyName, out double value)
    {
        value = 0;
        if (!parent.TryGetProperty(propertyName, out JsonElement element))
            return false;

        bool parsed = element.ValueKind == JsonValueKind.Number
            ? element.TryGetDouble(out value)
            : double.TryParse(element.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out value);
        return parsed && double.IsFinite(value);
    }

    private string WithRaw(string summary, JsonElement root)
    {
        if (!_settings.ShowRawJson)
            return summary;
        return summary + Environment.NewLine + Environment.NewLine + PrettyJson(root);
    }

    private static string OutputLabel(string label, int exitCode)
    {
        if (exitCode != 0)
        {
            return label switch
            {
                "validate" => "Validation failed",
                "dispatch" => "Dispatch rejected",
                "status" => "Status failed",
                _ => $"{label} failed",
            };
        }

        return label switch
        {
            "validate" => "Validated",
            "dispatch" => "Dispatch result",
            "status" => "Status",
            "continue" => "Continue result",
            "reissue" => "Reissue result",
            "cancel" => "Cancel result",
            "flat" => "FLAT result",
            _ => label,
        };
    }

    private bool Confirm(string text, bool defaultYes = false)
        => MessageBox.Show(this, text, "EAR Dispatcher",
            MessageBoxButtons.YesNo, MessageBoxIcon.Warning,
            defaultYes ? MessageBoxDefaultButton.Button1 : MessageBoxDefaultButton.Button2)
        == DialogResult.Yes;

    private static string FormatStatus(JsonElement root)
    {
        if (!root.TryGetProperty("runtime", out JsonElement runtime))
            return "status: invalid status payload";

        var lines = new List<string>
        {
            $"Runtime: {Str(runtime, "health")} | {Str(runtime, "state")} | {Str(runtime, "mode")}",
            $"Symbol: {Str(runtime, "execution_symbol")} from {Str(runtime, "market_data_symbol")} | max {Str(runtime, "instance_max_quantity")}",
        };

        if (root.TryGetProperty("position", out JsonElement position))
            lines.Add($"Position: qty {Str(position, "quantity")} avg {Str(position, "average_price")}");

        if (root.TryGetProperty("evidence", out JsonElement evidence))
            lines.Add($"Evidence: {Str(evidence, "state")} | samples {Str(evidence, "sample_count")}/{Str(evidence, "required_samples")} | warmup {Str(evidence, "warmup_remaining_seconds")}s");

        if (root.TryGetProperty("directive", out JsonElement directive))
        {
            lines.Add($"Directive: active {Str(directive, "active_id")} | last {Str(directive, "last_accepted_id")}");
            if (directive.TryGetProperty("last_outcome", out JsonElement lastOutcome)
                && lastOutcome.ValueKind == JsonValueKind.Object)
            {
                lines.Add($"Last directive: {FormatEventBrief(lastOutcome)}");
            }
        }

        if (root.TryGetProperty("last_control_outcome", out JsonElement lastControl)
            && lastControl.ValueKind == JsonValueKind.Object)
        {
            lines.Add($"Last control: {FormatEventBrief(lastControl)}");
        }

        string blockers = FormatBlockers(root);
        lines.Add(string.IsNullOrWhiteSpace(blockers) ? "Blockers: none" : blockers);

        if (root.TryGetProperty("recent_errors", out JsonElement recentErrors)
            && recentErrors.ValueKind == JsonValueKind.Array
            && recentErrors.GetArrayLength() > 0)
        {
            lines.Add("Recent material:");
            foreach (JsonElement item in recentErrors.EnumerateArray().Take(3))
                lines.Add($"- {FormatEventBrief(item)}");
        }

        return string.Join(Environment.NewLine, lines);
    }

    private static string FormatEventBrief(JsonElement item)
    {
        string eventName = Str(item, "event");
        string directiveId = Str(item, "directive_id");
        string commandId = Str(item, "command_id");
        string reason = Str(item, "reason");
        string message = Str(item, "message");
        var pieces = new List<string>();
        if (!string.IsNullOrWhiteSpace(eventName))
            pieces.Add(eventName);
        if (!string.IsNullOrWhiteSpace(directiveId))
            pieces.Add(directiveId);
        if (!string.IsNullOrWhiteSpace(commandId))
            pieces.Add(commandId);
        if (!string.IsNullOrWhiteSpace(reason))
            pieces.Add(reason);
        if (!string.IsNullOrWhiteSpace(message))
            pieces.Add(message);
        return pieces.Count == 0 ? item.ToString() : string.Join(" | ", pieces);
    }

    private static string FormatBlockers(JsonElement root)
    {
        if (!root.TryGetProperty("blockers", out JsonElement blockers)
            || blockers.ValueKind != JsonValueKind.Array
            || blockers.GetArrayLength() == 0)
        {
            return "";
        }

        var lines = new List<string> { "Blockers:" };
        foreach (JsonElement blocker in blockers.EnumerateArray())
            lines.Add($"- {Str(blocker, "code")}: {Str(blocker, "message")}");
        return string.Join(Environment.NewLine, lines);
    }

    private static string FormatLastAcceptedPriceScaleGuard(JsonElement root)
    {
        if (!root.TryGetProperty("directive", out JsonElement directive)
            || !directive.TryGetProperty("last_outcome", out JsonElement lastOutcome)
            || lastOutcome.ValueKind != JsonValueKind.Object)
        {
            return "";
        }

        var prices = new List<double>();
        AddPrice(lastOutcome, "order_price_lower", prices);
        AddPrice(lastOutcome, "order_price_upper", prices);
        AddPrice(lastOutcome, "context_price_lower", prices);
        AddPrice(lastOutcome, "context_price_upper", prices);
        AddPrice(lastOutcome, "add_price_lower", prices);
        AddPrice(lastOutcome, "add_price_upper", prices);
        AddPrice(lastOutcome, "target_price", prices);
        return FormatPriceScaleGuard(root, prices);
    }

    private static string FormatPriceScaleGuard(JsonElement root, IEnumerable<double> prices)
    {
        double[] finitePrices = prices
            .Where(price => double.IsFinite(price) && price > 0)
            .ToArray();
        if (finitePrices.Length == 0)
            return "";

        string symbol = RuntimeMarketDataSymbol(root);
        if (string.IsNullOrWhiteSpace(symbol))
            return "";

        double min = finitePrices.Min();
        double max = finitePrices.Max();
        string runtime = RuntimeSymbolLabel(root);
        if (IsEsLike(symbol) && max >= 10000)
        {
            return $"Price scale blocked: runtime is {runtime}, but the directive prices span {FormatDisplay(min)}-{FormatDisplay(max)}. "
                + "ES/MES prices should not be NQ-scale; check the base, sketch import, or reissue source.";
        }

        if (IsNqLike(symbol) && max < 10000)
        {
            return $"Price scale blocked: runtime is {runtime}, but the directive prices span {FormatDisplay(min)}-{FormatDisplay(max)}. "
                + "NQ/MNQ prices should not be ES-scale; check the base, sketch import, or reissue source.";
        }

        return "";
    }

    private static string FormatLastAcceptedDirectiveSummary(JsonElement root)
    {
        if (!root.TryGetProperty("directive", out JsonElement directive)
            || !directive.TryGetProperty("last_accepted_contract", out JsonElement contract)
            || contract.ValueKind != JsonValueKind.Object)
        {
            return "";
        }

        return RuntimeSymbolLabel(root) + Environment.NewLine
            + string.Join(Environment.NewLine, FormatDirectiveSummary(contract));
    }

    private static void AddPrice(JsonElement parent, string propertyName, List<double> prices)
    {
        if (TryGetFiniteDouble(parent, propertyName, out double price))
            prices.Add(price);
    }

    private static string RuntimeMarketDataSymbol(JsonElement root)
    {
        if (!root.TryGetProperty("runtime", out JsonElement runtime))
            return "";
        string marketDataSymbol = Str(runtime, "market_data_symbol");
        return string.IsNullOrWhiteSpace(marketDataSymbol)
            ? Str(runtime, "execution_symbol")
            : marketDataSymbol;
    }

    private static string RuntimeSymbolLabel(JsonElement root)
    {
        if (!root.TryGetProperty("runtime", out JsonElement runtime))
            return "Runtime: unknown symbol";
        string executionSymbol = Str(runtime, "execution_symbol");
        string marketDataSymbol = Str(runtime, "market_data_symbol");
        return string.IsNullOrWhiteSpace(marketDataSymbol)
            ? $"Runtime: {executionSymbol}"
            : $"Runtime: {executionSymbol} from {marketDataSymbol}";
    }

    private static bool IsEsLike(string symbol)
        => symbol.StartsWith("ES", StringComparison.OrdinalIgnoreCase)
            || symbol.StartsWith("MES", StringComparison.OrdinalIgnoreCase);

    private static bool IsNqLike(string symbol)
        => symbol.StartsWith("NQ", StringComparison.OrdinalIgnoreCase)
            || symbol.StartsWith("MNQ", StringComparison.OrdinalIgnoreCase);

    private static string FormatDispatchResult(JsonElement root, bool dryRun)
    {
        string outcome = Str(root, "outcome");
        string id = Str(root, "directive_id");
        if (string.IsNullOrWhiteSpace(id)
            && root.TryGetProperty("directive", out JsonElement directive))
        {
            id = Str(directive, "id");
        }

        var lines = new List<string>
        {
            dryRun && outcome == "validated" ? "Validated" : dryRun ? $"Validation: {outcome}" : $"Dispatch: {outcome}",
        };
        if (!string.IsNullOrWhiteSpace(id))
            lines.Add($"Directive: {id}");
        if (root.TryGetProperty("directive", out JsonElement contract)
            && contract.ValueKind == JsonValueKind.Object)
        {
            lines.AddRange(FormatDirectiveSummary(contract));
        }
        if (root.TryGetProperty("runtime_event", out JsonElement runtimeEvent)
            && runtimeEvent.ValueKind == JsonValueKind.Object)
        {
            lines.Add($"EAR: {Str(runtimeEvent, "event")} {Str(runtimeEvent, "reason")}".TrimEnd());
        }
        if (root.TryGetProperty("error", out JsonElement error))
            lines.Add($"Error: {error}");
        return string.Join(Environment.NewLine, lines);
    }

    private static IEnumerable<string> FormatDirectiveSummary(JsonElement directive)
    {
        string side = Str(directive, "side").ToUpperInvariant();
        if (directive.TryGetProperty("window", out JsonElement window))
            yield return $"Side: {side} | expires {Str(window, "expires_at")}";
        else
            yield return $"Side: {side}";

        if (directive.TryGetProperty("entry", out JsonElement entry))
        {
            yield return $"Order: {FormatRange(StrRange(entry, "order_price_range"))}";
            yield return $"Context: {FormatRange(StrRange(entry, "context_price_range"))}";
            string addRange = entry.TryGetProperty("add_price_range", out JsonElement add)
                && add.ValueKind == JsonValueKind.Object
                    ? FormatRange(StrRange(entry, "add_price_range"))
                    : "off";
            yield return $"Campaign: {addRange}";
        }

        if (directive.TryGetProperty("sizing", out JsonElement sizing))
        {
            yield return $"Qty: base {Str(sizing, "base_quantity")} add {Str(sizing, "add_quantity")} max {Str(sizing, "max_position_quantity")}";
        }

        if (directive.TryGetProperty("target", out JsonElement target))
        {
            string reference = Str(target, "reference");
            yield return string.IsNullOrWhiteSpace(reference)
                ? $"TP: {Str(target, "price")} {Str(target, "direction")}"
                : $"TP: {Str(target, "price")} {Str(target, "direction")} ({reference})";
        }

        string notes = Str(directive, "notes");
        if (!string.IsNullOrWhiteSpace(notes))
            yield return $"Notes: {notes}";
    }

    private static (string Lower, string Upper) StrRange(JsonElement parent, string property)
    {
        if (!parent.TryGetProperty(property, out JsonElement range)
            || range.ValueKind != JsonValueKind.Object)
        {
            return ("", "");
        }

        return (Str(range, "lower"), Str(range, "upper"));
    }

    private static string FormatRange((string Lower, string Upper) range)
        => string.IsNullOrWhiteSpace(range.Lower) && string.IsNullOrWhiteSpace(range.Upper)
            ? ""
            : $"{range.Lower}-{range.Upper}";

    private string FormatJsonCommandResult(CommandResult result, string idProperty)
    {
        string json = !string.IsNullOrWhiteSpace(result.Output) ? result.Output : result.Error;
        if (!TryParseJson(json, out JsonDocument? document))
            return result.DisplayText;

        using (document)
        {
            JsonElement root = document.RootElement;
            var lines = new List<string> { $"Outcome: {Str(root, "outcome")}" };
            string id = Str(root, idProperty);
            if (!string.IsNullOrWhiteSpace(id))
                lines.Add($"Id: {id}");
            if (root.TryGetProperty("runtime_event", out JsonElement runtimeEvent)
                && runtimeEvent.ValueKind == JsonValueKind.Object)
            {
                lines.Add($"EAR: {Str(runtimeEvent, "event")} {Str(runtimeEvent, "reason")}".TrimEnd());
            }
            if (root.TryGetProperty("error", out JsonElement error))
                lines.Add($"Error: {error}");
            return WithRaw(string.Join(Environment.NewLine, lines), root);
        }
    }

    private static bool TryParseJson(string text, [NotNullWhen(true)] out JsonDocument? document)
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

    private static string PrettyJson(JsonElement root)
        => JsonSerializer.Serialize(root, new JsonSerializerOptions { WriteIndented = true });

    private static bool TryInt(JsonElement parent, string property, out int value)
    {
        value = 0;
        if (!parent.TryGetProperty(property, out JsonElement element))
            return false;
        if (element.ValueKind == JsonValueKind.Number && element.TryGetInt32(out value))
            return true;
        return false;
    }

    private static string Str(JsonElement parent, string property)
    {
        if (!parent.TryGetProperty(property, out JsonElement element)
            || element.ValueKind == JsonValueKind.Null
            || element.ValueKind == JsonValueKind.Undefined)
        {
            return "";
        }

        return element.ValueKind == JsonValueKind.String
            ? element.GetString() ?? ""
            : element.ToString();
    }

    private static string FormatArg(double value)
        => value.ToString("0.########", CultureInfo.InvariantCulture);

    private static string FormatDisplay(double value)
        => value.ToString("0.00", CultureInfo.InvariantCulture);

    private static string FormatInputPrice(double price, double basePrice)
    {
        double shorthand = price - basePrice;
        if (shorthand >= 0 && shorthand < PriceInput.ShorthandLimit)
            return FormatArg(shorthand);
        return FormatArg(price);
    }

    private static ResolvedRange Envelope(ResolvedRange first, ResolvedRange second)
        => new(Math.Min(first.Lower, second.Lower), Math.Max(first.Upper, second.Upper));

    private static ResolvedRange CampaignRange(ResolvedRange context, double target, string side)
    {
        double contextEdge = side == "long" ? context.Lower : context.Upper;
        return new ResolvedRange(Math.Min(contextEdge, target), Math.Max(contextEdge, target));
    }

    private static Label PlainLabel(string text, int width = 48)
        => new()
        {
            Text = text,
            AutoSize = false,
            Width = width,
            Height = 24,
            TextAlign = ContentAlignment.MiddleLeft,
            AutoEllipsis = true,
            UseMnemonic = false,
            ForeColor = Palette.Muted,
            BackColor = Palette.Back,
            Margin = new Padding(0, 1, 6, 0),
        };

    private static Label PreviewLabel()
        => new()
        {
            AutoSize = false,
            Dock = DockStyle.Fill,
            Height = 24,
            TextAlign = ContentAlignment.MiddleLeft,
            AutoEllipsis = true,
            UseMnemonic = false,
            ForeColor = Palette.Muted,
            BackColor = Palette.Back,
            Margin = new Padding(0, 1, 8, 0),
        };

    private static TextBox Box(string text)
        => new()
        {
            Text = text,
            Width = 150,
            BackColor = Palette.Input,
            ForeColor = Palette.Fore,
            BorderStyle = BorderStyle.FixedSingle,
            Margin = new Padding(0, 2, 8, 2),
        };

    private static void AddLabel(TableLayoutPanel panel, string text, int column, int row)
    {
        panel.Controls.Add(new Label
        {
            Text = text,
            AutoSize = false,
            Dock = DockStyle.Fill,
            Height = 24,
            TextAlign = ContentAlignment.MiddleLeft,
            AutoEllipsis = true,
            UseMnemonic = false,
            ForeColor = Palette.Muted,
            BackColor = Palette.Back,
            Margin = new Padding(0, 1, 8, 0),
        }, column, row);
    }

    private static FlowLayoutPanel RowPanel(params Control[] controls)
    {
        var panel = new FlowLayoutPanel
        {
            AutoSize = true,
            Dock = DockStyle.Fill,
            BackColor = Palette.Back,
            Margin = new Padding(0),
            WrapContents = false,
        };
        panel.Controls.AddRange(controls);
        return panel;
    }

    private Button CommandButton(string text, EventHandler handler, bool danger = false)
    {
        var button = new Button
        {
            Text = text,
            AutoSize = true,
            TabStop = false,
            FlatStyle = FlatStyle.Flat,
            BackColor = danger ? Palette.Danger : Palette.Button,
            ForeColor = Palette.Fore,
            Margin = new Padding(0, 0, 8, 0),
        };
        button.FlatAppearance.BorderColor = danger ? Palette.DangerBorder : Palette.ButtonBorder;
        button.Click += (sender, args) =>
        {
            handler(sender, args);
            BeginInvoke(new Action(() => ActiveControl = _output));
        };
        return button;
    }

    private sealed record DispatchCommand(IReadOnlyList<string> Arguments, IReadOnlyList<double> Prices);

    private sealed record SketchImport(
        string Side,
        double OrderLower,
        double OrderUpper,
        double TargetPrice,
        string Signature);
}

internal static class PriceInput
{
    internal const double ShorthandLimit = 1000.0;

    private static readonly Regex RangeSeparator = new(
        @"\s*(?:-|\.{2}|\bto\b|\s+)\s*",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    public static ResolvedRange ParseRange(string text, double basePrice, string name)
    {
        string trimmed = text.Trim();
        if (trimmed.Length == 0)
            throw new InputException($"{name} range is empty");

        string[] parts = RangeSeparator
            .Split(trimmed)
            .Where(part => !string.IsNullOrWhiteSpace(part))
            .ToArray();
        if (parts.Length != 2)
            throw new InputException($"{name} range needs two prices");

        double first = ParsePrice(parts[0], basePrice, $"{name} lower");
        double second = ParsePrice(parts[1], basePrice, $"{name} upper");
        return first <= second
            ? new ResolvedRange(first, second)
            : new ResolvedRange(second, first);
    }

    public static double ParsePrice(string text, double basePrice, string name)
    {
        string trimmed = text.Trim();
        if (trimmed.Length == 0)
            throw new InputException($"{name} price is empty");
        if (!double.TryParse(trimmed, NumberStyles.Float, CultureInfo.InvariantCulture, out double raw)
            || !double.IsFinite(raw)
            || raw < 0)
        {
            throw new InputException($"{name} price is invalid");
        }

        return raw < ShorthandLimit ? basePrice + raw : raw;
    }
}

internal readonly record struct ResolvedRange(double Lower, double Upper);

internal sealed class InputException : Exception
{
    public InputException(string message)
        : base(message)
    {
    }
}

internal sealed class EarctlClient
{
    private readonly DispatcherSettings _settings;
    private readonly string _repoRoot;
    private readonly string _scriptPath;

    public EarctlClient(DispatcherSettings settings)
    {
        _settings = settings;
        _repoRoot = FindRepoRoot();
        _scriptPath = Path.Combine(_repoRoot, "skills", "exec-asst", "scripts", "earctl.py");
    }

    public async Task<CommandResult> RunAsync(IReadOnlyList<string> args)
    {
        if (!File.Exists(_scriptPath))
        {
            return new CommandResult(
                -1,
                "",
                $"earctl.py not found at {_scriptPath}");
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
            using var process = Process.Start(start);
            if (process is null)
                return new CommandResult(-1, "", "could not start python");

            Task<string> stdout = process.StandardOutput.ReadToEndAsync();
            Task<string> stderr = process.StandardError.ReadToEndAsync();
            await process.WaitForExitAsync();
            return new CommandResult(process.ExitCode, await stdout, await stderr);
        }
        catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception or IOException)
        {
            return new CommandResult(-1, "", ex.Message);
        }
    }

    private static string FindRepoRoot()
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string seed in new[] { AppContext.BaseDirectory, Environment.CurrentDirectory })
        {
            DirectoryInfo? dir = new DirectoryInfo(seed);
            while (dir is not null)
            {
                if (seen.Add(dir.FullName)
                    && File.Exists(Path.Combine(dir.FullName, "skills", "exec-asst", "scripts", "earctl.py")))
                {
                    return dir.FullName;
                }
                dir = dir.Parent;
            }
        }

        return Environment.CurrentDirectory;
    }
}

internal sealed record CommandResult(int ExitCode, string Output, string Error)
{
    public string DisplayText
    {
        get
        {
            var builder = new StringBuilder();
            if (!string.IsNullOrWhiteSpace(Output))
                builder.AppendLine(Output.TrimEnd());
            if (!string.IsNullOrWhiteSpace(Error))
                builder.AppendLine(Error.TrimEnd());
            if (builder.Length == 0)
                builder.Append("(no output)");
            return builder.ToString();
        }
    }
}

internal sealed class DispatcherSettings
{
    public string RuntimeDir { get; set; } =
        Environment.ExpandEnvironmentVariables(@"%USERPROFILE%\Documents\ExecAssistantRuntime");
    public string SketchDraftPath { get; set; } =
        Environment.ExpandEnvironmentVariables(@"%USERPROFILE%\Documents\ExecAssistantRuntime\directive-sketch-probe.json");
    public string PythonExe { get; set; } = "python";
    public string Side { get; set; } = "long";
    public string PriceBase { get; set; } = "30000";
    public string ContextRange { get; set; } = "";
    public string OrderRange { get; set; } = "";
    public string TargetPrice { get; set; } = "";
    public string TargetReference { get; set; } = "";
    public string InvalidationPrice { get; set; } = "";
    public bool CampaignEnabled { get; set; } = true;
    public bool AutoOrder { get; set; } = true;
    public bool AlwaysOnTop { get; set; }
    public bool ShowRawJson { get; set; }
    public int TimeoutMinutes { get; set; } = 30;
    public string BaseQuantity { get; set; } = "2";
    public string AddQuantity { get; set; } = "1";
    public string MaxPosition { get; set; } = "5";
    public bool UseRuntimeMax { get; set; } = true;
    public string Tag { get; set; } = "";
    public string Notes { get; set; } = "";

    [JsonIgnore]
    private static string SettingsPath
        => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Heatmap",
            "EarDispatcher",
            "settings.json");

    public static DispatcherSettings Load()
    {
        try
        {
            if (!File.Exists(SettingsPath))
                return new DispatcherSettings();
            string text = File.ReadAllText(SettingsPath);
            return JsonSerializer.Deserialize<DispatcherSettings>(text)
                ?? new DispatcherSettings();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            return new DispatcherSettings();
        }
    }

    public void Save()
    {
        try
        {
            string? directory = Path.GetDirectoryName(SettingsPath);
            if (!string.IsNullOrWhiteSpace(directory))
                Directory.CreateDirectory(directory);
            File.WriteAllText(
                SettingsPath,
                JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true }));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // Settings persistence is convenience only; dispatch behavior must not depend on it.
        }
    }
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
}
