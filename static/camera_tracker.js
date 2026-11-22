/* MediaPipe FaceLandmarker 100 % local : aucune image n'est envoyée ni enregistrée. */
window.CameraTracker = (() => {
  const V = "0.10.14", CDN = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${V}`;
  const MODEL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
  let lm, video, stream, raf, last = 0, closedSince = 0, ema = 80, cb;
  const bs = (c, n) => c.find(x => x.categoryName === n)?.score || 0;
  const avg = (c, a, b) => (bs(c, a) + bs(c, b)) / 2;

  async function start(el, onSample) {
    cb = onSample; video = el;
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240, facingMode: "user" } });
    video.srcObject = stream; await video.play();
    const { FaceLandmarker, FilesetResolver } = await import(`${CDN}/vision_bundle.mjs`);
    const fs = await FilesetResolver.forVisionTasks(`${CDN}/wasm`);
    const make = delegate => FaceLandmarker.createFromOptions(fs, {
      baseOptions: { modelAssetPath: MODEL, delegate }, runningMode: "VIDEO", numFaces: 1, outputFaceBlendshapes: true });
    try { lm = await make("GPU"); } catch { lm = await make("CPU"); }
    loop();
  }

  function loop() {
    raf = requestAnimationFrame(loop);
    const t = performance.now();
    if (t - last < 500 || video.readyState < 2) return;   // 2 analyses/s suffisent
    last = t;
    const r = lm.detectForVideo(video, t);
    if (!r.faceBlendshapes?.length) return emit(10, "absent", ["visage absent"]);
    const c = r.faceBlendshapes[0].categories, p = r.faceLandmarks[0], sig = [];
    const closed = avg(c, "eyeBlinkLeft", "eyeBlinkRight");
    const gaze = Math.max(
      (bs(c, "eyeLookOutLeft") + bs(c, "eyeLookInRight")) / 2, (bs(c, "eyeLookInLeft") + bs(c, "eyeLookOutRight")) / 2,
      avg(c, "eyeLookDownLeft", "eyeLookDownRight"), avg(c, "eyeLookUpLeft", "eyeLookUpRight"));
    const frown = avg(c, "browDownLeft", "browDownRight");
    const yaw = Math.abs((p[1].x - p[234].x) / (p[454].x - p[234].x) - 0.5) * 2;   // tête tournée
    if (closed > 0.6) closedSince ||= t; else closedSince = 0;
    let pen = 0;
    if (closedSince && t - closedSince > 1500) { pen += 40; sig.push("yeux fermés"); }
    if (gaze > 0.45) { pen += 30; sig.push("regard détourné"); }
    if (yaw > 0.35) { pen += 30; sig.push("tête tournée"); }
    if (frown > 0.4) { pen += 20; sig.push("sourcils froncés"); }
    emit(Math.max(0, 100 - pen), pen >= 30 ? "décroche" : pen ? "friction" : "attentif", sig);
  }

  function emit(raw, state, signals) {
    ema = 0.6 * ema + 0.4 * raw;           // lissage anti-bruit
    cb({ attention: ema, state, signals });
  }

  function stop() {
    cancelAnimationFrame(raf);
    stream?.getTracks().forEach(t => t.stop());
    lm?.close?.(); lm = null;
  }
  return { start, stop };
})();
