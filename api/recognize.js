export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "POST only" });
  }

  const token = process.env.AUDD_API_TOKEN;
  if (!token) {
    return res.status(503).json({
      ok: false,
      error: "AUDD_API_TOKEN が未設定です。VercelのEnvironment Variablesに設定してください。"
    });
  }

  try {
    const { audioBase64, mimeType = "audio/webm" } = req.body || {};

    if (!audioBase64) {
      return res.status(400).json({
        ok: false,
        error: "音声データがありません。"
      });
    }

    const bytes = Buffer.from(audioBase64, "base64");
    const form = new FormData();
    form.append("api_token", token);
    form.append(
      "file",
      new Blob([bytes], { type: mimeType }),
      mimeType.includes("ogg") ? "floor.ogg" : "floor.webm"
    );
    form.append("return", "spotify,apple_music");
    form.append("market", "jp");

    const upstream = await fetch("https://api.audd.io/", {
      method: "POST",
      body: form
    });

    const data = await upstream.json();

    if (!upstream.ok || data?.status !== "success") {
      return res.status(502).json({
        ok: false,
        error:
          data?.error?.error_message ||
          data?.error?.message ||
          `AudD API error (${upstream.status})`
      });
    }

    if (!data.result) {
      return res.status(200).json({ ok: true, match: null });
    }

    const r = data.result;
    return res.status(200).json({
      ok: true,
      match: {
        artist: r.artist || "",
        title: r.title || "",
        album: r.album || "",
        timecode: r.timecode || "",
        songLink: r.song_link || "",
        spotifyUrl: r.spotify?.external_urls?.spotify || "",
        appleMusicUrl: r.apple_music?.url || ""
      }
    });
  } catch (error) {
    return res.status(500).json({
      ok: false,
      error: error instanceof Error ? error.message : "認識処理エラー"
    });
  }
}
