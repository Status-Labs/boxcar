# Windows UI Automation helper — dumps actionable on-screen elements as JSON.
#
# Uses the built-in .NET UIAutomation client (no install needed). Writes the
# result to %USERPROFILE%\uia_out.json (a file, so it works whether run directly
# over SSH or via a scheduled task in the interactive session). Unlike Linux
# GTK4/AT-SPI, Windows UIA reports reliable on-screen rectangles.
#
#   powershell -File uia_helper.ps1 [maxElements]
param([int]$limit = 80)

$out = Join-Path $env:USERPROFILE "uia_out.json"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$AE = [System.Windows.Automation.AutomationElement]
$scopeDesc = [System.Windows.Automation.TreeScope]::Descendants
$scopeChild = [System.Windows.Automation.TreeScope]::Children
$true_ = [System.Windows.Automation.Condition]::TrueCondition

# Control types worth acting on.
$wanted = @("Button", "MenuItem", "ListItem", "Edit", "Hyperlink", "TabItem",
            "TreeItem", "CheckBox", "RadioButton", "ComboBox", "SplitButton")

$results = New-Object System.Collections.ArrayList
try {
    $windows = $AE::RootElement.FindAll($scopeChild, $true_)
    foreach ($w in $windows) {
        if ($results.Count -ge $limit) { break }
        $els = $w.FindAll($scopeDesc, $true_)
        foreach ($e in $els) {
            if ($results.Count -ge $limit) { break }
            try {
                $name = $e.Current.Name
                if (-not $name) { continue }
                $role = ($e.Current.ControlType.ProgrammaticName) -replace "ControlType.", ""
                if ($wanted -notcontains $role) { continue }
                if ($e.Current.IsOffscreen) { continue }
                $r = $e.Current.BoundingRectangle
                if ($r.Width -le 0 -or $r.Height -le 0) { continue }
                [void]$results.Add(@{
                    name = $name; role = $role
                    rect = @([int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height)
                })
            } catch { }
        }
    }
} catch { }

# @(...) forces a JSON array even for 0/1 elements.
ConvertTo-Json -InputObject @($results.ToArray()) -Compress -Depth 5 |
    Out-File -Encoding ascii $out
