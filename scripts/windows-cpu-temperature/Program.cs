using System.Text.Json;
using LibreHardwareMonitor.Hardware;

var computer = new Computer { IsCpuEnabled = true };
computer.Open();
try
{
    while (Console.ReadLine() is not null)
    {
        try
        {
            computer.Accept(new UpdateVisitor());
            var candidates = computer.Hardware
                .Where(hardware => hardware.HardwareType == HardwareType.Cpu)
                .SelectMany(hardware => hardware.Sensors
                    .Where(sensor => sensor.SensorType == SensorType.Temperature && sensor.Value.HasValue)
                    .Select(sensor => new { Hardware = hardware.Name, Sensor = sensor.Name, Value = sensor.Value!.Value }))
                .ToArray();

            var ranked = candidates
                .Select(sensor => new { Sensor = sensor, Rank = Rank(sensor.Sensor) })
                .Where(item => item.Rank < int.MaxValue)
                .OrderBy(item => item.Rank)
                .Select(item => item.Sensor)
                .ToArray();

            var selected = ranked.FirstOrDefault(sensor => float.IsFinite(sensor.Value) && sensor.Value > 0 && sensor.Value <= 125);
            var diagnosticSensor = selected ?? ranked.FirstOrDefault();
            var sensorStatus = selected is not null ? "ok" : diagnosticSensor is null ? "sensor_not_found" : "invalid_reading";
            var response = new
            {
                value_c = selected is not null ? (float?)selected.Value : null,
                sensor = diagnosticSensor is not null ? $"{diagnosticSensor.Hardware}/{diagnosticSensor.Sensor}" : null,
                status = sensorStatus,
                source = "LibreHardwareMonitor"
            };
            Console.WriteLine(JsonSerializer.Serialize(response));
            Console.Out.Flush();
        }
        catch (Exception exception)
        {
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                value_c = (float?)null,
                sensor = (string?)null,
                status = "read_error",
                source = "LibreHardwareMonitor",
                error = exception.GetType().Name
            }));
            Console.Out.Flush();
        }
    }
}
finally
{
    computer.Close();
}

static int Rank(string name)
{
    var normalized = name.Replace(" ", "", StringComparison.Ordinal).Replace("/", "", StringComparison.Ordinal).ToLowerInvariant();
    if (normalized.Contains("tctltdie")) return 0;
    if (normalized.Contains("tctl") || normalized.Contains("tdie")) return 1;
    if (normalized.Contains("package")) return 2;
    return int.MaxValue;
}

sealed class UpdateVisitor : IVisitor
{
    public void VisitComputer(IComputer computer) => computer.Traverse(this);
    public void VisitHardware(IHardware hardware)
    {
        hardware.Update();
        foreach (var subHardware in hardware.SubHardware)
            subHardware.Accept(this);
    }
    public void VisitSensor(ISensor sensor) { }
    public void VisitParameter(IParameter parameter) { }
}
