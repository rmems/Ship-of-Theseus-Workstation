using System.Text.Json;
using LibreHardwareMonitor.Hardware;

var computer = new Computer { IsCpuEnabled = true };
try
{
    computer.Open();
    while (Console.ReadLine() is not null)
    {
        Console.WriteLine(JsonSerializer.Serialize(ReadTemperature(computer)));
        Console.Out.Flush();
    }
}
finally
{
    computer.Close();
}

static TemperatureResponse ReadTemperature(Computer computer)
{
    try
    {
        computer.Accept(new UpdateVisitor());
        var ranked = computer.Hardware
            .Where(hardware => hardware.HardwareType == HardwareType.Cpu)
            .SelectMany(CpuSensors)
            .Where(sensor => sensor.SensorType == SensorType.Temperature)
            .Where(sensor => Rank(sensor.Name) < int.MaxValue)
            .OrderBy(sensor => Rank(sensor.Name))
            .ToArray();
        var selected = ranked.FirstOrDefault(sensor => ValidTemperature(sensor.Value));
        return BuildResponse(selected, ranked.FirstOrDefault());
    }
    catch (Exception exception)
    {
        return new TemperatureResponse(null, null, "read_error", error: exception.GetType().Name);
    }
}

static IEnumerable<ISensor> CpuSensors(IHardware hardware)
{
    return hardware.Sensors.Concat(hardware.SubHardware.SelectMany(CpuSensors));
}

static bool ValidTemperature(float? value)
{
    return value.HasValue && float.IsFinite(value.Value) && value.Value > 0 && value.Value <= 125;
}

static TemperatureResponse BuildResponse(ISensor? selected, ISensor? diagnostic)
{
    var sensor = selected ?? diagnostic;
    var label = sensor is null ? null : $"{sensor.Hardware.Name}/{sensor.Name}";
    if (selected is not null)
        return new TemperatureResponse(selected.Value, label, "ok");
    return new TemperatureResponse(null, label, sensor is null ? "sensor_not_found" : "invalid_reading");
}

static int Rank(string name)
{
    var normalized = name.Replace(" ", "", StringComparison.Ordinal).Replace("/", "", StringComparison.Ordinal).ToLowerInvariant();
    if (normalized.Contains("tctltdie")) return 0;
    if (normalized.Contains("tctl") || normalized.Contains("tdie")) return 1;
    if (normalized.Contains("package")) return 2;
    return int.MaxValue;
}

sealed record TemperatureResponse(float? value_c, string? sensor, string status,
                                  string source = "LibreHardwareMonitor", string? error = null);

sealed class UpdateVisitor : IVisitor
{
    public void VisitComputer(IComputer computer) => computer.Traverse(this);
    public void VisitHardware(IHardware hardware)
    {
        hardware.Update();
        foreach (var subHardware in hardware.SubHardware)
            subHardware.Accept(this);
    }
    public void VisitSensor(ISensor sensor)
    {
        // Hardware.Update() refreshes sensor values; no per-sensor action is needed.
    }
    public void VisitParameter(IParameter parameter)
    {
        // This read-only visitor never changes hardware parameters.
    }
}
