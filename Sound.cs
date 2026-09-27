using System.Media;

namespace CargoDeckScanner;

// Leise, weiche Töne statt dem lauten Systempiepen
static class Sound
{
    public enum Kind { On, Off, Success, Error, Queued }
    public const Kind On = Kind.On, Off = Kind.Off, Success = Kind.Success, Error = Kind.Error, Queued = Kind.Queued;

    static readonly Dictionary<Kind, byte[]> Cache = new();
    static SoundPlayer _player;

    public static void Play(Kind kind)
    {
        try
        {
            if (!Cache.TryGetValue(kind, out var wav))
            {
                wav = kind switch
                {
                    Kind.On => Make((660, 0, 0.09), (880, 0.07, 0.14)),
                    Kind.Off => Make((740, 0, 0.09), (554, 0.07, 0.14)),
                    Kind.Success => Make((784, 0, 0.08), (988, 0.06, 0.08), (1319, 0.12, 0.18)),
                    Kind.Queued => Make((698, 0, 0.12)),   // ein einzelner, kurzer, leiser Ton
                    _ => Make((330, 0, 0.16)),
                };
                Cache[kind] = wav;
            }
            _player?.Stop();
            _player = new SoundPlayer(new MemoryStream(wav));
            _player.Play();
        }
        catch { }
    }

    // Noten als (Frequenz, Start in s, Länge in s), weicher Einsatz und Ausklang, sehr leise
    static byte[] Make(params (double f, double start, double len)[] notes)
    {
        const int rate = 44100; const double vol = 0.07;
        double total = notes.Max(n => n.start + n.len) + 0.03;
        int count = (int)(total * rate);
        var samples = new double[count];
        foreach (var (f, start, len) in notes)
        {
            int s0 = (int)(start * rate), n = (int)(len * rate);
            for (int i = 0; i < n && s0 + i < count; i++)
            {
                double t = (double)i / rate;
                double env = Math.Min(1, t / 0.008) * Math.Exp(-t * 18 / Math.Max(len, 0.05) * 0.35) * Math.Min(1, (n - i) / (0.02 * rate));
                samples[s0 + i] += env * (Math.Sin(2 * Math.PI * f * t) + 0.25 * Math.Sin(4 * Math.PI * f * t));
            }
        }
        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms);
        w.Write("RIFF"u8.ToArray()); w.Write(36 + count * 2); w.Write("WAVE"u8.ToArray());
        w.Write("fmt "u8.ToArray()); w.Write(16); w.Write((short)1); w.Write((short)1); w.Write(rate); w.Write(rate * 2); w.Write((short)2); w.Write((short)16);
        w.Write("data"u8.ToArray()); w.Write(count * 2);
        foreach (var v in samples) w.Write((short)Math.Clamp(v * vol * 32767, -32767, 32767));
        w.Flush();
        return ms.ToArray();
    }
}
