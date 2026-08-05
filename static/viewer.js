/* Vue 3D WebGL2 — conteneur, colis, orbite, sélection et déplacement manuel.
   Aucune dépendance externe : tout est écrit ici (matrices, shaders, picking).
   Repère : X = longueur, Y = largeur, Z = hauteur (vers le haut), en centimètres. */

/* ───────────────────────── algèbre ───────────────────────── */
const M4 = {
  ident: () => new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]),
  mul(a, b) {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      o[c * 4 + r] = s;
    }
    return o;
  },
  perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return new Float32Array([f/aspect,0,0,0, 0,f,0,0, 0,0,(far+near)*nf,-1, 0,0,2*far*near*nf,0]);
  },
  lookAt(eye, center, up) {
    const z = norm(sub(eye, center)), x = norm(cross(up, z)), y = cross(z, x);
    return new Float32Array([
      x[0], y[0], z[0], 0,
      x[1], y[1], z[1], 0,
      x[2], y[2], z[2], 0,
      -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]);
  },
  invert(m) {
    const o = new Float32Array(16), a = m;
    const b00=a[0]*a[5]-a[1]*a[4],  b01=a[0]*a[6]-a[2]*a[4],  b02=a[0]*a[7]-a[3]*a[4];
    const b03=a[1]*a[6]-a[2]*a[5],  b04=a[1]*a[7]-a[3]*a[5],  b05=a[2]*a[7]-a[3]*a[6];
    const b06=a[8]*a[13]-a[9]*a[12],b07=a[8]*a[14]-a[10]*a[12],b08=a[8]*a[15]-a[11]*a[12];
    const b09=a[9]*a[14]-a[10]*a[13],b10=a[9]*a[15]-a[11]*a[13],b11=a[10]*a[15]-a[11]*a[14];
    let det = b00*b11-b01*b10+b02*b09+b03*b08-b04*b07+b05*b06;
    if (!det) return M4.ident();
    det = 1 / det;
    o[0]=(a[5]*b11-a[6]*b10+a[7]*b09)*det;  o[1]=(a[2]*b10-a[1]*b11-a[3]*b09)*det;
    o[2]=(a[13]*b05-a[14]*b04+a[15]*b03)*det; o[3]=(a[10]*b04-a[9]*b05-a[11]*b03)*det;
    o[4]=(a[6]*b08-a[4]*b11-a[7]*b07)*det;  o[5]=(a[0]*b11-a[2]*b08+a[3]*b07)*det;
    o[6]=(a[14]*b02-a[12]*b05-a[15]*b01)*det; o[7]=(a[8]*b05-a[10]*b02+a[11]*b01)*det;
    o[8]=(a[4]*b10-a[5]*b08+a[7]*b06)*det;  o[9]=(a[1]*b08-a[0]*b10-a[3]*b06)*det;
    o[10]=(a[12]*b04-a[13]*b02+a[15]*b00)*det;o[11]=(a[9]*b02-a[8]*b04-a[11]*b00)*det;
    o[12]=(a[5]*b07-a[4]*b09-a[6]*b06)*det; o[13]=(a[0]*b09-a[1]*b07+a[2]*b06)*det;
    o[14]=(a[13]*b01-a[12]*b03-a[14]*b00)*det;o[15]=(a[8]*b03-a[9]*b01+a[10]*b00)*det;
    return o;
  },
};
const sub=(a,b)=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]];
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const norm=v=>{const l=Math.hypot(...v)||1; return [v[0]/l,v[1]/l,v[2]/l];};

/* ───────────────────────── shaders ───────────────────────── */
const VS = `#version 300 es
in vec3 aPos; in vec3 aNormal; in vec3 aColor; in float aFlag;
uniform mat4 uVP;
out vec3 vN; out vec3 vC; out float vF; out vec3 vW;
void main(){ vN=aNormal; vC=aColor; vF=aFlag; vW=aPos; gl_Position=uVP*vec4(aPos,1.0); }`;

const FS = `#version 300 es
precision highp float;
in vec3 vN; in vec3 vC; in float vF; in vec3 vW;
out vec4 outColor;
void main(){
  vec3 n = normalize(vN);
  vec3 l1 = normalize(vec3(0.45, 0.30, 0.84));
  vec3 l2 = normalize(vec3(-0.6, -0.5, 0.30));
  float d = 0.62 + 0.42*max(dot(n,l1),0.0) + 0.16*max(dot(n,l2),0.0);
  vec3 c = vC * d;
  if (vF > 1.5)      c = mix(c, vec3(0.86,0.30,0.20), 0.55);   // position invalide
  else if (vF > 0.5) c = mix(c, vec3(1.0,0.86,0.36), 0.42);    // colis sélectionné
  outColor = vec4(c, 1.0);
}`;

const VS_LINE = `#version 300 es
in vec3 aPos; in vec3 aColor;
uniform mat4 uVP;
out vec3 vC;
void main(){ vC=aColor; gl_Position=uVP*vec4(aPos,1.0); gl_Position.z -= 0.0006*gl_Position.w; }`;

const FS_LINE = `#version 300 es
precision highp float;
in vec3 vC; out vec4 outColor;
void main(){ outColor = vec4(vC, 1.0); }`;

const FS_PICK = `#version 300 es
precision highp float;
in vec3 vN; in vec3 vC; in float vF; in vec3 vW;
out vec4 outColor;
void main(){ outColor = vec4(vC, 1.0); }`;   // vC transporte l'identifiant encodé

const FS_SHADOW = `#version 300 es
precision highp float;
in vec3 vN; in vec3 vC; in float vF; in vec3 vW;
out vec4 outColor;
void main(){ outColor = vec4(0.06,0.14,0.17,0.13); }`;

/* ───────────────────────── viewer ───────────────────────── */
export function creerViewer(canvas, opts = {}) {
  const gl = canvas.getContext("webgl2", { antialias: true, alpha: true, premultipliedAlpha: false });
  if (!gl) { canvas.parentElement.innerHTML =
      '<p style="padding:32px;text-align:center;color:#7C9099">WebGL 2 indisponible dans ce navigateur.</p>'; return null; }

  const compiler = (type, src) => {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  };
  const lier = (vs, fs) => {
    const p = gl.createProgram();
    gl.attachShader(p, compiler(gl.VERTEX_SHADER, vs));
    gl.attachShader(p, compiler(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    return p;
  };

  const pSolid = lier(VS, FS), pPick = lier(VS, FS_PICK),
        pShadow = lier(VS, FS_SHADOW), pLine = lier(VS_LINE, FS_LINE);

  // --- buffers
  const mk = () => ({ vao: gl.createVertexArray(), pos: gl.createBuffer(), nor: gl.createBuffer(),
                      col: gl.createBuffer(), flg: gl.createBuffer(), idx: gl.createBuffer(), n: 0 });
  const geo = mk(), pick = mk(), shadow = mk();
  const lignes = { vao: gl.createVertexArray(), pos: gl.createBuffer(), col: gl.createBuffer(), n: 0 };

  function brancher(g, prog) {
    gl.bindVertexArray(g.vao);
    const attr = (buf, nom, taille) => {
      const loc = gl.getAttribLocation(prog, nom);
      if (loc < 0) return;
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, taille, gl.FLOAT, false, 0, 0);
    };
    attr(g.pos, "aPos", 3); attr(g.nor, "aNormal", 3); attr(g.col, "aColor", 3); attr(g.flg, "aFlag", 1);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, g.idx);
    gl.bindVertexArray(null);
  }

  // --- framebuffer de sélection
  const fbo = gl.createFramebuffer(), texPick = gl.createTexture(), rbo = gl.createRenderbuffer();

  const NORMALES = [[0,0,1],[0,0,-1],[1,0,0],[-1,0,0],[0,1,0],[0,-1,0]];
  const FACES = [
    [[0,0,1],[1,0,1],[1,1,1],[0,1,1]], [[0,1,0],[1,1,0],[1,0,0],[0,0,0]],
    [[1,0,0],[1,1,0],[1,1,1],[1,0,1]], [[0,1,0],[0,0,0],[0,0,1],[0,1,1]],
    [[1,1,0],[0,1,0],[0,1,1],[1,1,1]], [[0,0,0],[1,0,0],[1,0,1],[0,0,1]],
  ];

  function construireBoites(boites, couleurs, flags) {
    const nb = boites.length;
    const P = new Float32Array(nb*24*3), N = new Float32Array(nb*24*3),
          C = new Float32Array(nb*24*3), F = new Float32Array(nb*24),
          Cp = new Float32Array(nb*24*3), I = new Uint32Array(nb*36);
    const Sp = new Float32Array(nb*24*3), Sn = new Float32Array(nb*24*3),
          Sc = new Float32Array(nb*24*3), Sf = new Float32Array(nb*24), Si = new Uint32Array(nb*36);
    let vi = 0, ii = 0, sv = 0, si = 0, nOmbre = 0;
    boites.forEach((b, k) => {
      const col = couleurs[k], id = k + 1;
      const idc = [((id) & 255)/255, ((id >> 8) & 255)/255, ((id >> 16) & 255)/255];
      FACES.forEach((f, fi) => {
        const base = vi/3;
        f.forEach(([ux, uy, uz]) => {
          P[vi] = b.x + ux*b.l; P[vi+1] = b.y + uy*b.w; P[vi+2] = b.z + uz*b.h;
          N[vi] = NORMALES[fi][0]; N[vi+1] = NORMALES[fi][1]; N[vi+2] = NORMALES[fi][2];
          C[vi] = col[0]; C[vi+1] = col[1]; C[vi+2] = col[2];
          Cp[vi] = idc[0]; Cp[vi+1] = idc[1]; Cp[vi+2] = idc[2];
          F[vi/3] = flags[k];
          vi += 3;
        });
        I[ii++] = base; I[ii++] = base+1; I[ii++] = base+2;
        I[ii++] = base; I[ii++] = base+2; I[ii++] = base+3;
      });
      if (b.z > 0.5) {                       // empreinte projetée au sol
        const base = sv/3;
        [[0,0],[1,0],[1,1],[0,1]].forEach(([ux, uy]) => {
          Sp[sv] = b.x + ux*b.l; Sp[sv+1] = b.y + uy*b.w; Sp[sv+2] = 0.4;
          Sn[sv] = 0; Sn[sv+1] = 0; Sn[sv+2] = 1; Sc[sv] = 0; Sc[sv+1] = 0; Sc[sv+2] = 0;
          Sf[sv/3] = 0; sv += 3;
        });
        Si[si++] = base; Si[si++] = base+1; Si[si++] = base+2;
        Si[si++] = base; Si[si++] = base+2; Si[si++] = base+3;
        nOmbre++;
      }
    });

    const up = (g, p, n, c, f, idx, count) => {
      gl.bindBuffer(gl.ARRAY_BUFFER, g.pos); gl.bufferData(gl.ARRAY_BUFFER, p, gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, g.nor); gl.bufferData(gl.ARRAY_BUFFER, n, gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, g.col); gl.bufferData(gl.ARRAY_BUFFER, c, gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, g.flg); gl.bufferData(gl.ARRAY_BUFFER, f, gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, g.idx); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.DYNAMIC_DRAW);
      g.n = count;
    };
    up(geo, P, N, C, F, I, nb*36);
    up(pick, P, N, Cp, F, I, nb*36);
    up(shadow, Sp.subarray(0, nOmbre*12), Sn.subarray(0, nOmbre*12), Sc.subarray(0, nOmbre*12),
       Sf.subarray(0, nOmbre*4), Si.subarray(0, nOmbre*6), nOmbre*6);
    brancher(geo, pSolid); brancher(pick, pPick); brancher(shadow, pShadow);
  }

  function construireLignes(boites, dims) {
    const P = [], C = [];
    const arete = (a, b, c) => { P.push(...a, ...b); C.push(...c, ...c); };
    const cadre = (x, y, z, l, w, h, c) => {
      const p = (i, j, k) => [x + i*l, y + j*w, z + k*h];
      [[0,0,0,1,0,0],[0,1,0,1,1,0],[0,0,1,1,0,1],[0,1,1,1,1,1]].forEach(v=>arete(p(v[0],v[1],v[2]),p(v[3],v[4],v[5]),c));
      [[0,0,0,0,1,0],[1,0,0,1,1,0],[0,0,1,0,1,1],[1,0,1,1,1,1]].forEach(v=>arete(p(v[0],v[1],v[2]),p(v[3],v[4],v[5]),c));
      [[0,0,0,0,0,1],[1,0,0,1,0,1],[0,1,0,0,1,1],[1,1,0,1,1,1]].forEach(v=>arete(p(v[0],v[1],v[2]),p(v[3],v[4],v[5]),c));
    };
    const [L, W, H] = dims;
    const cGrille = [0.80, 0.85, 0.86], cCadre = [0.42, 0.53, 0.56], cColis = [0.20, 0.32, 0.36];
    for (let x = 100; x < L; x += 100) arete([x, 0, 0], [x, W, 0], cGrille);
    for (let y = 100; y < W; y += 100) arete([0, y, 0], [L, y, 0], cGrille);
    cadre(0, 0, 0, L, W, H, cCadre);
    boites.forEach(b => cadre(b.x, b.y, b.z, b.l, b.w, b.h, cColis));
    gl.bindVertexArray(lignes.vao);
    const attr = (buf, arr, nom) => {
      gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(arr), gl.DYNAMIC_DRAW);
      const loc = gl.getAttribLocation(pLine, nom);
      gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 3, gl.FLOAT, false, 0, 0);
    };
    attr(lignes.pos, P, "aPos"); attr(lignes.col, C, "aColor");
    gl.bindVertexArray(null);
    lignes.n = P.length / 3;
  }

  /* ── état ── */
  const V = {
    dims: [1203.4, 235.2, 270], boites: [], couleurs: [], flags: [],
    cam: { az: -0.72, el: 0.55, dist: 1900, cible: [600, 118, 100] },
    selection: -1, invalide: false, visibles: 1e9,
    onSelect: opts.onSelect || (() => {}),
    onMove: opts.onMove || (() => {}),
    editable: false,
  };

  function eye() {
    const { az, el, dist, cible } = V.cam;
    return [cible[0] + dist*Math.cos(el)*Math.cos(az),
            cible[1] + dist*Math.cos(el)*Math.sin(az),
            cible[2] + dist*Math.sin(el)];
  }
  function matrices() {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const w = Math.max(1, canvas.clientWidth), h = Math.max(1, canvas.clientHeight);
    if (canvas.width !== w*dpr || canvas.height !== h*dpr) {
      canvas.width = w*dpr; canvas.height = h*dpr;
      gl.bindTexture(gl.TEXTURE_2D, texPick);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, canvas.width, canvas.height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      gl.bindRenderbuffer(gl.RENDERBUFFER, rbo);
      gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT16, canvas.width, canvas.height);
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texPick, 0);
      gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, rbo);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    }
    const P = M4.perspective(38*Math.PI/180, w/h, 20, 20000);
    const Vw = M4.lookAt(eye(), V.cam.cible, [0, 0, 1]);
    return { VP: M4.mul(P, Vw), w: canvas.width, h: canvas.height };
  }

  function rendu() {
    const { VP, w, h } = matrices();
    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE); gl.cullFace(gl.BACK);

    const nVis = Math.min(V.visibles, V.boites.length) * 36;

    gl.useProgram(pShadow);
    gl.uniformMatrix4fv(gl.getUniformLocation(pShadow, "uVP"), false, VP);
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false);
    gl.bindVertexArray(shadow.vao);
    gl.drawElements(gl.TRIANGLES, shadow.n, gl.UNSIGNED_INT, 0);
    gl.depthMask(true); gl.disable(gl.BLEND);

    gl.useProgram(pSolid);
    gl.uniformMatrix4fv(gl.getUniformLocation(pSolid, "uVP"), false, VP);
    gl.bindVertexArray(geo.vao);
    gl.drawElements(gl.TRIANGLES, nVis, gl.UNSIGNED_INT, 0);

    gl.useProgram(pLine);
    gl.uniformMatrix4fv(gl.getUniformLocation(pLine, "uVP"), false, VP);
    gl.bindVertexArray(lignes.vao);
    gl.drawArrays(gl.LINES, 0, lignes.n);
    gl.bindVertexArray(null);
  }

  function viser(px, py) {
    const { VP, w, h } = matrices();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE);
    gl.useProgram(pPick);
    gl.uniformMatrix4fv(gl.getUniformLocation(pPick, "uVP"), false, VP);
    gl.bindVertexArray(pick.vao);
    gl.drawElements(gl.TRIANGLES, Math.min(V.visibles, V.boites.length)*36, gl.UNSIGNED_INT, 0);
    const buf = new Uint8Array(4);
    const dpr = Math.min(devicePixelRatio || 1, 2);
    gl.readPixels(Math.round(px*dpr), h - Math.round(py*dpr), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, buf);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.bindVertexArray(null);
    const id = buf[0] + (buf[1] << 8) + (buf[2] << 16);
    return id ? id - 1 : -1;
  }

  function rayon(px, py) {
    const { VP } = matrices();
    const inv = M4.invert(VP);
    const nx = (px / canvas.clientWidth) * 2 - 1, ny = 1 - (py / canvas.clientHeight) * 2;
    const proj = (z) => {
      const x = inv[0]*nx + inv[4]*ny + inv[8]*z + inv[12];
      const y = inv[1]*nx + inv[5]*ny + inv[9]*z + inv[13];
      const w = inv[3]*nx + inv[7]*ny + inv[11]*z + inv[15];
      const zz = inv[2]*nx + inv[6]*ny + inv[10]*z + inv[14];
      return [x/w, y/w, zz/w];
    };
    const a = proj(-1), b = proj(1);
    return { o: a, d: norm(sub(b, a)) };
  }
  function surPlan(px, py, zPlan) {
    const { o, d } = rayon(px, py);
    if (Math.abs(d[2]) < 1e-6) return null;
    const t = (zPlan - o[2]) / d[2];
    if (t < 0) return null;
    return [o[0] + d[0]*t, o[1] + d[1]*t];
  }

  /* ── interactions ── */
  let mode = null, dep = null, boiteDep = null, grab = null, bougé = false;

  canvas.addEventListener("contextmenu", e => e.preventDefault());
  canvas.addEventListener("pointerdown", e => {
    canvas.setPointerCapture(e.pointerId);
    const r = canvas.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
    dep = { x: e.clientX, y: e.clientY, az: V.cam.az, el: V.cam.el, cible: [...V.cam.cible] };
    bougé = false;
    if (e.button === 2 || e.shiftKey) { mode = "pan"; return; }
    const id = viser(px, py);
    if (V.editable && id >= 0) {
      V.selection = id; V.onSelect(id);
      const b = V.boites[id];
      const p = surPlan(px, py, b.z);
      if (p) { mode = "drag"; boiteDep = { ...b }; grab = [p[0] - b.x, p[1] - b.y]; majFlags(); rendu(); return; }
    }
    mode = "orbit";
    if (id < 0 && V.selection !== -1) { V.selection = -1; V.onSelect(-1); majFlags(); }
    rendu();
  });

  canvas.addEventListener("pointermove", e => {
    const r = canvas.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
    if (!mode) {
      if (V.editable) {
        const id = viser(px, py);
        canvas.style.cursor = id >= 0 ? "grab" : "default";
        if (opts.onHover) opts.onHover(id, e.clientX, e.clientY);
      }
      return;
    }
    const dx = e.clientX - dep.x, dy = e.clientY - dep.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) bougé = true;
    if (mode === "orbit") {
      V.cam.az = dep.az - dx*0.006;
      V.cam.el = Math.max(-0.25, Math.min(1.45, dep.el + dy*0.005));
    } else if (mode === "pan") {
      const s = V.cam.dist * 0.0011;
      const ct = Math.cos(V.cam.az), st = Math.sin(V.cam.az);
      V.cam.cible = [dep.cible[0] + (dx*st + dy*ct*Math.sin(V.cam.el))*s,
                     dep.cible[1] + (-dx*ct + dy*st*Math.sin(V.cam.el))*s,
                     dep.cible[2] + dy*Math.cos(V.cam.el)*s];
    } else if (mode === "drag") {
      const b = V.boites[V.selection];
      const p = surPlan(px, py, boiteDep.z);
      if (p) {
        b.x = Math.round(p[0] - grab[0]);
        b.y = Math.round(p[1] - grab[1]);
        contraindre(b);
        construireBoites(V.boites, V.couleurs, V.flags);
        construireLignes(V.boites.slice(0, V.visibles), V.dims);
      }
    }
    rendu();
  });

  const finir = () => {
    if (mode === "drag" && bougé) {
      const b = V.boites[V.selection];
      if (V.invalide) { Object.assign(b, boiteDep); majFlags(); reconstruire(); }
      V.onMove(V.selection, V.invalide);
    }
    mode = null; canvas.style.cursor = "default";
  };
  canvas.addEventListener("pointerup", finir);
  canvas.addEventListener("pointercancel", finir);
  canvas.addEventListener("wheel", e => {
    e.preventDefault();
    V.cam.dist = Math.max(180, Math.min(9000, V.cam.dist * (1 + Math.sign(e.deltaY)*0.11)));
    rendu();
  }, { passive: false });

  function contraindre(b) {
    const [L, W, H] = V.dims;
    b.x = Math.max(0, Math.min(L - b.l, b.x));
    b.y = Math.max(0, Math.min(W - b.w, b.y));
    V.invalide = !valide(b, V.selection);
    majFlags();
  }
  function valide(b, moi) {
    for (let i = 0; i < V.boites.length; i++) {
      if (i === moi) continue;
      const o = V.boites[i];
      if (b.x + b.l > o.x + 0.01 && o.x + o.l > b.x + 0.01 &&
          b.y + b.w > o.y + 0.01 && o.y + o.w > b.y + 0.01 &&
          b.z + b.h > o.z + 0.01 && o.z + o.h > b.z + 0.01) return false;
    }
    if (b.z <= 0.5) return true;
    let aire = 0;
    for (let i = 0; i < V.boites.length; i++) {
      if (i === moi) continue;
      const o = V.boites[i];
      if (Math.abs(o.z + o.h - b.z) > 1) continue;
      aire += Math.max(0, Math.min(b.x+b.l, o.x+o.l) - Math.max(b.x, o.x)) *
              Math.max(0, Math.min(b.y+b.w, o.y+o.w) - Math.max(b.y, o.y));
    }
    return aire >= 0.7 * b.l * b.w;
  }
  function majFlags() {
    V.flags = V.boites.map((_, i) =>
      i === V.selection ? (V.invalide && mode === "drag" ? 2 : 1) : 0);
  }
  function reconstruire() {
    construireBoites(V.boites, V.couleurs, V.flags);
    construireLignes(V.boites.slice(0, V.visibles), V.dims);
    rendu();
  }

  /* Ajuste la distance pour que le conteneur remplisse le cadre : on projette
     ses 8 sommets et on corrige jusqu'à ce qu'ils tiennent juste dans l'écran.
     Une sphère englobante donnerait un cadrage trop lâche sur un objet long. */
  function ajuster(marge = 0.90) {
    const [L, W, H] = V.dims;
    const coins = [[0,0,0],[L,0,0],[0,W,0],[L,W,0],[0,0,H],[L,0,H],[0,W,H],[L,W,H]];
    for (let k = 0; k < 4; k++) {
      const { VP } = matrices();
      let m = 0;
      for (const [X, Y, Z] of coins) {
        const w = VP[3]*X + VP[7]*Y + VP[11]*Z + VP[15];
        if (w <= 0) { m = 2; break; }
        m = Math.max(m, Math.abs((VP[0]*X + VP[4]*Y + VP[8]*Z + VP[12]) / w),
                        Math.abs((VP[1]*X + VP[5]*Y + VP[9]*Z + VP[13]) / w));
      }
      if (!m) break;
      V.cam.dist = Math.max(150, Math.min(9000, V.cam.dist * m / marge));
      if (Math.abs(m - marge) < 0.02) break;
    }
  }

  /* ── api ── */
  return {
    definir(dims, boites, couleurs) {
      V.dims = dims; V.boites = boites.map(b => ({ ...b }));
      V.couleurs = couleurs; V.selection = -1; V.visibles = boites.length;
      V.invalide = false; majFlags(); reconstruire();
    },
    cadrer() {
      const [L, W, H] = V.dims;
      V.cam.cible = [L/2, W/2, H/2];
      V.cam.dist = Math.hypot(L, W, H);
      V.cam.az = -0.72; V.cam.el = 0.42;
      ajuster(); rendu();
    },
    vue(nom) {
      const p = { troisquart: [-0.72, 0.42], dessus: [-Math.PI/2, 1.45],
                  cote: [-Math.PI/2, 0.05], arriere: [Math.PI, 0.20], avant: [0, 0.20] }[nom];
      if (!p) return;
      const [L, W, H] = V.dims;
      V.cam.az = p[0]; V.cam.el = p[1]; V.cam.cible = [L/2, W/2, H/2];
      ajuster(nom === "troisquart" ? 0.90 : 0.94); rendu();
    },
    visibles(n) { V.visibles = n; reconstruire(); },
    editable(v) { V.editable = v; if (!v) { V.selection = -1; majFlags(); reconstruire(); } },
    selectionner(i) { V.selection = i; majFlags(); reconstruire(); },
    selection: () => V.selection,
    boites: () => V.boites,
    deplacer(i, dx, dy) {
      const b = V.boites[i]; if (!b) return false;
      const sauve = { ...b };
      b.x += dx; b.y += dy;
      const sel = V.selection; V.selection = i;
      contraindre(b);
      if (V.invalide) { Object.assign(b, sauve); V.invalide = false; majFlags(); reconstruire(); V.selection = sel; return false; }
      V.selection = sel; reconstruire(); return true;
    },
    pivoter(i) {
      const b = V.boites[i]; if (!b) return false;
      const sauve = { ...b };
      const cx = b.x + b.l/2, cy = b.y + b.w/2;
      [b.l, b.w] = [b.w, b.l];
      b.x = Math.round(cx - b.l/2); b.y = Math.round(cy - b.w/2);
      const sel = V.selection; V.selection = i;
      contraindre(b);
      if (V.invalide) { Object.assign(b, sauve); V.invalide = false; majFlags(); reconstruire(); V.selection = sel; return false; }
      V.selection = sel; reconstruire(); return true;
    },
    viser: (px, py) => viser(px, py),
    rendu,
  };
}
