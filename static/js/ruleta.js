/**
 * Ruleta de la Suerte — componente de dibujo y animación en <canvas>.
 *
 *   const ruleta = new Ruleta(canvas, [{ id, texto, color }, ...]);
 *   await ruleta.girarA(indice);   // gira y se detiene en el premio indicado
 *
 * El componente NO decide el premio: solo anima hasta el índice que devuelve
 * el servidor. Así el resultado no se puede manipular desde el navegador.
 */
(function (global) {
    'use strict';

    const DOS_PI = Math.PI * 2;
    const ORO = '#e8c790';
    const ORO_OSCURO = '#ad6e25';
    const FUENTE = 'Manrope, system-ui, sans-serif';
    const reducirMovimiento = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    /** Desaceleración suave: arranca rápido y frena poco a poco (ease-out quint). */
    const easeOut = (t) => 1 - Math.pow(1 - t, 5);

    /** Texto negro o blanco según la luminancia del color de fondo (HEX #rrggbb). */
    function colorTexto(hex) {
        const n = parseInt(hex.slice(1), 16);
        const canal = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
        const l = 0.2126 * canal(n >> 16) + 0.7152 * canal((n >> 8) & 255) + 0.0722 * canal(n & 255);
        return l > 0.38 ? '#07150f' : '#ffffff';
    }

    /** Aclara (+) u oscurece (-) un color HEX. */
    function matiz(hex, cantidad) {
        const n = parseInt(hex.slice(1), 16);
        const ajustar = (c) => Math.max(0, Math.min(255, Math.round(c + 255 * cantidad)));
        return `rgb(${ajustar(n >> 16)}, ${ajustar((n >> 8) & 255)}, ${ajustar(n & 255)})`;
    }

    class Ruleta {
        constructor(canvas, premios, opciones = {}) {
            this.canvas = canvas;
            this.ctx = canvas.getContext('2d');
            this.premios = premios || [];
            this.rotacion = 0;          // radianes, sentido horario
            this.girando = false;
            this.golpe = 0;             // rebote de la flecha al pasar cada segmento
            this.alTic = opciones.alTic || null;

            // Re-dibuja nítido en pantallas retina y al cambiar el tamaño
            this._ajustarTamano();
            if ('ResizeObserver' in window) {
                new ResizeObserver(() => { this._ajustarTamano(); this.dibujar(); }).observe(canvas);
            }
            // La fuente web puede cargar después del primer dibujo
            if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => this.dibujar());
            this.dibujar();
        }

        setPremios(premios) {
            this.premios = premios || [];
            this.dibujar();
        }

        get arco() { return DOS_PI / Math.max(this.premios.length, 1); }

        /** Índice del premio que está bajo la flecha con la rotación actual. */
        indiceBajoFlecha(rotacion = this.rotacion) {
            const angulo = ((-rotacion % DOS_PI) + DOS_PI) % DOS_PI;
            return Math.floor(angulo / this.arco) % Math.max(this.premios.length, 1);
        }

        /**
         * Gira la ruleta y se detiene en el premio `indice`.
         * @returns {Promise<void>} se resuelve cuando la ruleta se detiene.
         */
        girarA(indice) {
            if (this.girando || !this.premios.length) return Promise.resolve();
            this.girando = true;

            // Punto de parada dentro del segmento, sin rozar los bordes (no parece "trucado")
            const desvio = (Math.random() - 0.5) * this.arco * 0.7;
            const destino = ((DOS_PI - (indice + 0.5) * this.arco - desvio) % DOS_PI + DOS_PI) % DOS_PI;
            const actual = ((this.rotacion % DOS_PI) + DOS_PI) % DOS_PI;
            const vueltas = reducirMovimiento() ? 1 : 6 + Math.floor(Math.random() * 3);
            const inicio = this.rotacion;
            const recorrido = vueltas * DOS_PI + ((destino - actual + DOS_PI) % DOS_PI);
            const duracion = reducirMovimiento() ? 1200 : 6500 + Math.random() * 1000;

            return new Promise((resolver) => {
                const t0 = performance.now();
                let ultimoIndice = this.indiceBajoFlecha();
                const paso = (ahora) => {
                    const t = Math.min((ahora - t0) / duracion, 1);
                    this.rotacion = inicio + recorrido * easeOut(t);

                    const indiceActual = this.indiceBajoFlecha();
                    if (indiceActual !== ultimoIndice) {
                        ultimoIndice = indiceActual;
                        this.golpe = 1;
                        if (this.alTic) this.alTic();
                    }
                    this.golpe *= 0.82;
                    this.dibujar(ahora);

                    if (t < 1) {
                        requestAnimationFrame(paso);
                    } else {
                        this.rotacion %= DOS_PI;
                        this.girando = false;
                        this._asentarFlecha(resolver);
                    }
                };
                requestAnimationFrame(paso);
            });
        }

        /** Deja que la flecha termine su rebote antes de anunciar el premio. */
        _asentarFlecha(listo) {
            const asentar = () => {
                this.golpe *= 0.75;
                this.dibujar();
                if (this.golpe > 0.01) requestAnimationFrame(asentar);
                else { this.golpe = 0; this.dibujar(); listo(); }
            };
            requestAnimationFrame(asentar);
        }

        _ajustarTamano() {
            const dpr = Math.min(window.devicePixelRatio || 1, 3);
            const lado = Math.max(this.canvas.clientWidth, 120);
            this.canvas.width = Math.round(lado * dpr);
            this.canvas.height = Math.round(lado * dpr);
            this.escala = dpr;
            this.lado = lado;
        }

        /* ------------------------------------------------------------------
         * DIBUJO
         * ------------------------------------------------------------------ */
        dibujar(ahora = performance.now()) {
            const { ctx, lado } = this;
            ctx.setTransform(this.escala, 0, 0, this.escala, 0, 0);
            ctx.clearRect(0, 0, lado, lado);

            const cx = lado / 2;
            const cy = lado / 2 + lado * 0.025;     // deja aire arriba para la flecha
            const radio = lado * 0.43;

            this._dibujarAro(cx, cy, radio, ahora);
            if (this.premios.length) this._dibujarSegmentos(cx, cy, radio);
            else this._dibujarVacio(cx, cy, radio);
            this._dibujarCentro(cx, cy, radio);
            this._dibujarFlecha(cx, cy - radio, radio);
        }

        _dibujarAro(cx, cy, radio, ahora) {
            const { ctx } = this;
            const grosor = radio * 0.09;

            // Sombra de la ruleta sobre el fondo
            ctx.save();
            ctx.shadowColor = 'rgba(0,0,0,.55)';
            ctx.shadowBlur = radio * 0.18;
            ctx.shadowOffsetY = radio * 0.05;
            ctx.beginPath();
            ctx.arc(cx, cy, radio + grosor, 0, DOS_PI);
            ctx.fillStyle = '#0c241a';
            ctx.fill();
            ctx.restore();

            // Aro dorado
            const oro = ctx.createLinearGradient(cx - radio, cy - radio, cx + radio, cy + radio);
            oro.addColorStop(0, '#f3dcae');
            oro.addColorStop(0.45, ORO_OSCURO);
            oro.addColorStop(0.7, ORO);
            oro.addColorStop(1, '#7a4a12');
            ctx.beginPath();
            ctx.arc(cx, cy, radio + grosor, 0, DOS_PI);
            ctx.arc(cx, cy, radio, 0, DOS_PI, true);
            ctx.fillStyle = oro;
            ctx.fill();

            // Foquitos: parpadean alternados mientras gira
            const focos = 24;
            const fase = this.girando ? Math.floor(ahora / 140) % 2 : -1;
            for (let i = 0; i < focos; i++) {
                const a = (i / focos) * DOS_PI;
                const x = cx + Math.cos(a) * (radio + grosor / 2);
                const y = cy + Math.sin(a) * (radio + grosor / 2);
                const encendido = fase === -1 || i % 2 === fase;
                ctx.beginPath();
                ctx.arc(x, y, grosor * 0.24, 0, DOS_PI);
                ctx.fillStyle = encendido ? '#fffbe9' : '#8d5617';
                if (encendido) { ctx.shadowColor = '#ffe6a8'; ctx.shadowBlur = grosor * 0.6; }
                ctx.fill();
                ctx.shadowBlur = 0;
            }
        }

        _dibujarSegmentos(cx, cy, radio) {
            const { ctx, premios, arco } = this;
            const base = -Math.PI / 2 + this.rotacion;   // el segmento 0 empieza arriba

            premios.forEach((premio, i) => {
                const a0 = base + i * arco;
                const a1 = a0 + arco;

                // Segmento con un leve degradado radial para dar volumen
                const relleno = ctx.createRadialGradient(cx, cy, radio * 0.15, cx, cy, radio);
                relleno.addColorStop(0, matiz(premio.color, 0.12));
                relleno.addColorStop(1, matiz(premio.color, -0.06));
                ctx.beginPath();
                ctx.moveTo(cx, cy);
                ctx.arc(cx, cy, radio, a0, a1);
                ctx.closePath();
                ctx.fillStyle = relleno;
                ctx.fill();

                // Separadores
                ctx.strokeStyle = 'rgba(255,255,255,.55)';
                ctx.lineWidth = Math.max(1, radio * 0.008);
                ctx.stroke();

                this._dibujarTexto(premio, cx, cy, radio, a0 + arco / 2);
            });

            // Brillo superior (efecto cristal)
            const brillo = ctx.createLinearGradient(0, cy - radio, 0, cy + radio);
            brillo.addColorStop(0, 'rgba(255,255,255,.18)');
            brillo.addColorStop(0.5, 'rgba(255,255,255,0)');
            brillo.addColorStop(1, 'rgba(0,0,0,.12)');
            ctx.beginPath();
            ctx.arc(cx, cy, radio, 0, DOS_PI);
            ctx.fillStyle = brillo;
            ctx.fill();
        }

        /** Texto a lo largo del radio, en 1 o 2 líneas, reduciendo la letra si hace falta. */
        _dibujarTexto(premio, cx, cy, radio, angulo) {
            const { ctx } = this;
            const exterior = radio * 0.9;
            const anchoMax = radio * 0.62;                       // del borde hacia el centro
            const altoArco = 2 * radio * 0.62 * Math.sin(this.arco / 2); // espacio vertical disponible
            let tam = Math.min(radio * 0.085, altoArco * 0.42);

            const partir = (tamano) => {
                ctx.font = `800 ${tamano}px ${FUENTE}`;
                if (ctx.measureText(premio.texto).width <= anchoMax) return [premio.texto];
                const palabras = premio.texto.split(' ');
                let mejor = null;
                for (let k = 1; k < palabras.length; k++) {
                    const l1 = palabras.slice(0, k).join(' ');
                    const l2 = palabras.slice(k).join(' ');
                    const ancho = Math.max(ctx.measureText(l1).width, ctx.measureText(l2).width);
                    if (!mejor || ancho < mejor.ancho) mejor = { lineas: [l1, l2], ancho };
                }
                return mejor && mejor.ancho <= anchoMax ? mejor.lineas : null;
            };

            let lineas = partir(tam);
            while (!lineas && tam > 8) { tam -= 0.5; lineas = partir(tam); }
            if (!lineas) {
                // Último recurso: una línea recortada con puntos suspensivos
                let t = premio.texto;
                while (t.length > 1 && ctx.measureText(t + '…').width > anchoMax) t = t.slice(0, -1);
                lineas = [t + '…'];
            }
            if (lineas.length === 2 && tam * 2.2 > altoArco) lineas = [lineas.join(' ')]; // sin espacio para 2 líneas

            ctx.save();
            ctx.translate(cx, cy);
            ctx.rotate(angulo);
            ctx.textAlign = 'right';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = colorTexto(premio.color);
            ctx.shadowColor = ctx.fillStyle === '#ffffff' ? 'rgba(0,0,0,.35)' : 'rgba(255,255,255,.25)';
            ctx.shadowBlur = 2;
            const interlinea = tam * 1.1;
            lineas.forEach((linea, i) => {
                ctx.fillText(linea, exterior, (i - (lineas.length - 1) / 2) * interlinea);
            });
            ctx.restore();
        }

        _dibujarVacio(cx, cy, radio) {
            const { ctx } = this;
            ctx.beginPath();
            ctx.arc(cx, cy, radio, 0, DOS_PI);
            ctx.fillStyle = '#123326';
            ctx.fill();
        }

        _dibujarCentro(cx, cy, radio) {
            const { ctx } = this;
            const r = radio * 0.17;
            ctx.save();
            ctx.shadowColor = 'rgba(0,0,0,.5)';
            ctx.shadowBlur = r * 0.5;
            const fondo = ctx.createRadialGradient(cx - r * 0.3, cy - r * 0.3, r * 0.1, cx, cy, r);
            fondo.addColorStop(0, '#256148');
            fondo.addColorStop(1, '#07150f');
            ctx.beginPath();
            ctx.arc(cx, cy, r, 0, DOS_PI);
            ctx.fillStyle = fondo;
            ctx.fill();
            ctx.restore();

            ctx.beginPath();
            ctx.arc(cx, cy, r, 0, DOS_PI);
            ctx.lineWidth = r * 0.14;
            ctx.strokeStyle = ORO;
            ctx.stroke();

            // Estrella dorada central
            ctx.beginPath();
            for (let i = 0; i < 10; i++) {
                const a = -Math.PI / 2 + (i * Math.PI) / 5;
                const rr = i % 2 === 0 ? r * 0.55 : r * 0.23;
                ctx.lineTo(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr);
            }
            ctx.closePath();
            ctx.fillStyle = ORO;
            ctx.fill();
        }

        /** Flecha superior fija; rebota un poco cada vez que pasa un segmento. */
        _dibujarFlecha(x, yBorde, radio) {
            const { ctx } = this;
            const ancho = radio * 0.13;
            const alto = radio * 0.2;
            const pivote = yBorde - radio * 0.07;

            ctx.save();
            ctx.translate(x, pivote);
            ctx.rotate(-this.golpe * 0.45);
            ctx.shadowColor = 'rgba(0,0,0,.5)';
            ctx.shadowBlur = radio * 0.04;
            ctx.shadowOffsetY = radio * 0.015;

            ctx.beginPath();
            ctx.moveTo(-ancho, 0);
            ctx.quadraticCurveTo(0, -ancho * 0.9, ancho, 0);
            ctx.lineTo(0, alto);
            ctx.closePath();
            const metal = ctx.createLinearGradient(-ancho, 0, ancho, 0);
            metal.addColorStop(0, '#f3dcae');
            metal.addColorStop(0.5, '#c98a3c');
            metal.addColorStop(1, '#7a4a12');
            ctx.fillStyle = metal;
            ctx.fill();
            ctx.shadowColor = 'transparent';
            ctx.lineWidth = Math.max(1, radio * 0.01);
            ctx.strokeStyle = '#07150f';
            ctx.stroke();

            ctx.beginPath();
            ctx.arc(0, 0, ancho * 0.28, 0, DOS_PI);
            ctx.fillStyle = '#07150f';
            ctx.fill();
            ctx.restore();
        }
    }

    /* ----------------------------------------------------------------------
     * Extras de celebración
     * ---------------------------------------------------------------------- */

    /** Lluvia de confeti sobre toda la pantalla (se omite con movimiento reducido). */
    function lanzarConfeti(colores) {
        if (reducirMovimiento()) return;
        const lienzo = document.createElement('canvas');
        lienzo.setAttribute('aria-hidden', 'true');
        lienzo.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:60';
        document.body.appendChild(lienzo);
        const ctx = lienzo.getContext('2d');
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        lienzo.width = innerWidth * dpr;
        lienzo.height = innerHeight * dpr;
        ctx.scale(dpr, dpr);

        const paleta = (colores && colores.length ? colores : []).concat(['#e8c790', '#c98a3c', '#6fd8a9', '#f6f3ec']);
        const piezas = Array.from({ length: 160 }, () => ({
            x: innerWidth / 2 + (Math.random() - 0.5) * 120,
            y: innerHeight * 0.4,
            vx: (Math.random() - 0.5) * 16,
            vy: -Math.random() * 15 - 5,
            giro: Math.random() * DOS_PI,
            vgiro: (Math.random() - 0.5) * 0.4,
            ancho: 6 + Math.random() * 6,
            color: paleta[Math.floor(Math.random() * paleta.length)],
        }));
        const t0 = performance.now();
        (function cuadro(ahora) {
            const t = ahora - t0;
            ctx.clearRect(0, 0, innerWidth, innerHeight);
            ctx.globalAlpha = Math.max(0, 1 - t / 3200);
            piezas.forEach((p) => {
                p.vy += 0.38; p.vx *= 0.985; p.x += p.vx; p.y += p.vy; p.giro += p.vgiro;
                ctx.save();
                ctx.translate(p.x, p.y);
                ctx.rotate(p.giro);
                ctx.fillStyle = p.color;
                ctx.fillRect(-p.ancho / 2, -p.ancho / 4, p.ancho, p.ancho / 2);
                ctx.restore();
            });
            if (t < 3200) requestAnimationFrame(cuadro); else lienzo.remove();
        })(t0);
    }

    /** "Tic" corto de la flecha con Web Audio (sin archivos de sonido). */
    function crearSonidoTic() {
        const Contexto = window.AudioContext || window.webkitAudioContext;
        if (!Contexto) return () => {};
        let audio = null;
        return function tic() {
            try {
                audio = audio || new Contexto();
                const osc = audio.createOscillator();
                const vol = audio.createGain();
                osc.type = 'triangle';
                osc.frequency.value = 1400 + Math.random() * 200;
                vol.gain.setValueAtTime(0.06, audio.currentTime);
                vol.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + 0.05);
                osc.connect(vol).connect(audio.destination);
                osc.start();
                osc.stop(audio.currentTime + 0.06);
            } catch (e) { /* sin sonido */ }
        };
    }

    global.Ruleta = Ruleta;
    global.Ruleta.lanzarConfeti = lanzarConfeti;
    global.Ruleta.crearSonidoTic = crearSonidoTic;
})(window);
