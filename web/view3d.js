// LUNAR//OPS 3D view (Stage 13). An illustration that never decides anything:
// terrain = NASA LOLA heights around the site (8 x 8 km, true vertical scale);
// the skyline ring, the Sun and Earth positions and the landing-point colours all
// come from the engine's precomputed results, so the picture cannot disagree with them.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const RING_M = 3900;      // the engine's skyline (300 km of terrain) drawn as a ring at the patch edge

export function createView(container, colors) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  container.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.5, 60000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.maxPolarAngle = Math.PI * 0.495;
  scene.add(new THREE.HemisphereLight(0x9aa3b5, 0x202020, 0.35));
  const sunLight = new THREE.DirectionalLight(0xffffff, 2.2);
  scene.add(sunLight, sunLight.target);

  let terrain = null, ring = null, pins = [], sunMark = null, earthMark = null, eye = 1, grid = null, lander = false;
  const dirOf = (az, el) => {
    const a = THREE.MathUtils.degToRad(az), e = THREE.MathUtils.degToRad(el);
    return new THREE.Vector3(Math.sin(a) * Math.cos(e), Math.sin(e), -Math.cos(a) * Math.cos(e));
  };
  const heightAt = (x, z) => {                       // bilinear on the patch grid (x east, z = -north)
    if (!grid) return 0;
    const { n, step, half, h } = grid;
    const c = (x + half) / step, r = (z + half) / step;
    const c0 = Math.max(0, Math.min(n - 2, Math.floor(c))), r0 = Math.max(0, Math.min(n - 2, Math.floor(r)));
    const tx = c - c0, ty = r - r0, at = (rr, cc) => h[rr * n + cc];
    return (1 - ty) * ((1 - tx) * at(r0, c0) + tx * at(r0, c0 + 1)) + ty * ((1 - tx) * at(r0 + 1, c0) + tx * at(r0 + 1, c0 + 1));
  };

  function setSite(t3d, buf, horizonCdeg, eyeHeight) {
    for (const o of [terrain, ring, sunMark, earthMark, ...pins]) if (o) { scene.remove(o); o.geometry?.dispose(); }
    pins = [];
    const n = t3d.n, raw = new Int16Array(buf), h = Float32Array.from(raw, (v) => v * t3d.scale_m);
    grid = { n, step: t3d.step_m, half: t3d.half_m, h };
    eye = eyeHeight;
    const g = new THREE.PlaneGeometry(2 * t3d.half_m, 2 * t3d.half_m, n - 1, n - 1);
    g.rotateX(-Math.PI / 2);                         // plane +y (north) -> -z
    const pos = g.attributes.position;
    for (let i = 0; i < pos.count; i++) pos.setY(i, h[i]);
    g.computeVertexNormals();
    terrain = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0x9c9a96, roughness: 1, metalness: 0 }));
    scene.add(terrain);
    // skyline ring: elevation angle seen from the lander's eye, drawn at RING_M
    const pts = [];
    for (let k = 0; k <= horizonCdeg.length; k += 4) {
      const kk = k % horizonCdeg.length, az = (kk * 360) / horizonCdeg.length, el = horizonCdeg[kk] / 100;
      const d = dirOf(az, 0);
      pts.push(new THREE.Vector3(d.x * RING_M, eye + Math.tan(THREE.MathUtils.degToRad(el)) * RING_M, d.z * RING_M));
    }
    ring = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: colors.ring }));
    scene.add(ring);
    // true angular radii (Sun 0.27 deg, Earth 0.95 deg) at RING_M; enlarged 4x in the overview so they stay visible
    const mark = (deg, c) => new THREE.Mesh(new THREE.SphereGeometry(Math.tan(THREE.MathUtils.degToRad(deg)) * RING_M, 32, 16), new THREE.MeshBasicMaterial({ color: c }));
    sunMark = mark(0.267, colors.sun); earthMark = mark(0.95, colors.earth);
    for (const m of [sunMark, earthMark]) m.scale.setScalar(lander ? 1 : 4);
    scene.add(sunMark, earthMark);
    for (const [k, [ex, ny]] of t3d.points_enu_m.entries()) {
      const y = heightAt(ex, -ny);
      const pin = new THREE.Mesh(new THREE.CylinderGeometry(k ? 10 : 16, k ? 10 : 16, k ? 120 : 220, 12),
        new THREE.MeshBasicMaterial({ color: 0xffffff }));
      pin.position.set(ex, y + (k ? 60 : 110), -ny);
      scene.add(pin); pins.push(pin);
    }
    if (!lander) { camera.position.set(-1500, 1100, 1900); controls.target.set(0, -80, 0); }
    controls.update();
  }

  function setTime(sun, earth, sunVisible) {
    if (!sunMark) return;
    const ds = dirOf(sun.az, sun.el), de = dirOf(earth.az, earth.el);
    sunMark.position.set(ds.x * RING_M, eye + ds.y / Math.hypot(ds.x, ds.z) * RING_M, ds.z * RING_M);
    earthMark.position.set(de.x * RING_M, eye + de.y / Math.hypot(de.x, de.z) * RING_M, de.z * RING_M);
    sunLight.position.copy(ds.clone().multiplyScalar(20000));
    sunLight.intensity = sun.el > -1 ? 2.2 : 0;        // grazing light; local cast shadows are not simulated
    sunMark.material.color.set(sunVisible ? colors.sun : colors.hidden);
  }

  function setPoints(pass) {
    pins.forEach((p, k) => p.material.color.set(pass[k] == null ? 0xffffff : pass[k] ? colors.ok : colors.bad));
  }

  function landerView(on, sunAz) {
    lander = on;
    pins.forEach((p) => (p.visible = !on));
    for (const m of [sunMark, earthMark]) m?.scale.setScalar(on ? 1 : 4);
    if (on) {
      const d = dirOf(sunAz, 0);
      camera.fov = 22; camera.updateProjectionMatrix();
      // eye at the panel/antenna height the skyline was computed for; target 1 m ahead so dragging looks around
      camera.position.set(-d.x, eye, -d.z);
      controls.target.set(0, eye, 0);
      controls.enableZoom = false; controls.enablePan = false;
      controls.maxPolarAngle = Math.PI;
    } else {
      camera.fov = 45; camera.updateProjectionMatrix();
      controls.enableZoom = true; controls.enablePan = true;
      controls.maxPolarAngle = Math.PI * 0.495;
      camera.position.set(-1500, 1100, 1900); controls.target.set(0, -80, 0);
    }
    controls.update();
  }

  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  // Render on demand only: when the view is on screen AND something changed (camera, time, site).
  // A continuous 60 fps loop over a 160 000-vertex mesh was what made the whole page stutter.
  let dirty = true, visible = false, idle = 0;
  const invalidate = () => { dirty = true; idle = 0; if (visible) renderer.setAnimationLoop(loop); };
  function loop() {
    const moved = controls.update();                 // true while damping is still settling
    if (moved || dirty) { renderer.render(scene, camera); dirty = false; idle = 0; }
    else if (++idle > 30) renderer.setAnimationLoop(null);   // stop until the next change
  }
  controls.addEventListener("change", invalidate);
  controls.addEventListener("start", invalidate);
  new IntersectionObserver((es) => { visible = es.some((e) => e.isIntersecting); visible ? invalidate() : renderer.setAnimationLoop(null); }).observe(container);
  new ResizeObserver(() => { resize(); invalidate(); }).observe(container);
  resize();
  const api = { setSite, setTime, setPoints, landerView };
  for (const k of Object.keys(api)) { const f = api[k]; api[k] = (...a) => { const r = f(...a); invalidate(); return r; }; }
  return api;
}
