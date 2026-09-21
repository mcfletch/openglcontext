/* Rotate the slides of every `.gallery-rotate` on the page.
 *
 * The slides are in the page already -- a documentation page is as often read
 * from a checkout over file:// as from the published site, and a browser will
 * not fetch a sibling file from there, so a gallery that loaded its list would
 * be empty for exactly the readers who have the repository.  This adds the
 * rotation, the controls and the keyboard to markup that already shows its
 * first slide without any of them.
 *
 * Rotation stops while the reader is looking at something (hover, focus), while
 * the gallery is off screen, and entirely when the platform asks for reduced
 * motion; the controls stay in every case.
 */
(function () {
    'use strict';

    var STILL = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function Gallery(root) {
        this.root = root;
        this.slides = Array.prototype.slice.call(root.querySelectorAll('.slide'));
        if (this.slides.length < 2) { return; }
        this.index = 0;
        this.interval = parseInt(root.getAttribute('data-interval'), 10) || 6000;
        this.timer = null;
        this.held = false;         // pointer or focus is on the gallery
        this.onScreen = true;
        this.build();
        this.show(0);
        this.watch();
        this.resume();
    }

    Gallery.prototype.build = function () {
        var self = this;
        var frame = document.createElement('div');
        frame.className = 'frame';
        this.slides[0].parentNode.insertBefore(frame, this.slides[0]);
        this.slides.forEach(function (slide) { frame.appendChild(slide); });
        this.frame = frame;

        var controls = document.createElement('div');
        controls.className = 'controls';

        function button(label, title, handler) {
            var b = document.createElement('button');
            b.type = 'button';
            b.textContent = label;
            b.setAttribute('title', title);
            b.setAttribute('aria-label', title);
            b.addEventListener('click', handler);
            controls.appendChild(b);
            return b;
        }

        button('‹', 'Previous picture', function () { self.step(-1); });
        button('›', 'Next picture', function () { self.step(1); });

        this.dots = document.createElement('div');
        this.dots.className = 'dots';
        this.slides.forEach(function (slide, i) {
            var b = document.createElement('button');
            b.type = 'button';
            b.setAttribute('title', 'Picture ' + (i + 1) + ' of ' + self.slides.length);
            b.setAttribute('aria-label', b.getAttribute('title'));
            b.addEventListener('click', function () { self.show(i); self.restart(); });
            self.dots.appendChild(b);
        });
        controls.appendChild(this.dots);

        this.root.appendChild(controls);
        this.root.classList.add('is-live');
        this.root.setAttribute('role', 'region');
        this.root.setAttribute('tabindex', '0');
        if (!this.root.hasAttribute('aria-label')) {
            this.root.setAttribute('aria-label', 'Gallery of rendered pictures');
        }
    };

    Gallery.prototype.watch = function () {
        var self = this;
        /* The picture is its own control: which half of it was clicked is which
         * way to go.  Only a click on the picture counts, so the caption under
         * it stays selectable text. */
        this.frame.addEventListener('click', function (event) {
            var image = event.target;
            if (!image || image.tagName !== 'IMG') { return; }
            var box = image.getBoundingClientRect();
            self.step(event.clientX < box.left + box.width / 2 ? -1 : 1);
        });
        ['mouseenter', 'focusin'].forEach(function (name) {
            self.root.addEventListener(name, function () { self.held = true; self.pause(); });
        });
        ['mouseleave', 'focusout'].forEach(function (name) {
            self.root.addEventListener(name, function () { self.held = false; self.resume(); });
        });
        this.root.addEventListener('keydown', function (event) {
            if (event.key === 'ArrowLeft') { self.step(-1); event.preventDefault(); }
            else if (event.key === 'ArrowRight') { self.step(1); event.preventDefault(); }
        });
        if (window.IntersectionObserver) {
            new window.IntersectionObserver(function (entries) {
                self.onScreen = entries[entries.length - 1].isIntersecting;
                if (self.onScreen) { self.resume(); } else { self.pause(); }
            }).observe(this.root);
        }
        document.addEventListener('visibilitychange', function () {
            if (document.hidden) { self.pause(); } else { self.resume(); }
        });
    };

    Gallery.prototype.load = function (index) {
        var slide = this.slides[(index + this.slides.length) % this.slides.length];
        var image = slide && slide.querySelector('img[data-src]');
        if (image) {
            image.src = image.getAttribute('data-src');
            image.removeAttribute('data-src');
        }
    };

    Gallery.prototype.show = function (index) {
        var self = this;
        this.index = (index + this.slides.length) % this.slides.length;
        /* The first slide loads with the page; the rest load as they are wanted,
         * one ahead so the fade never opens onto an empty frame. */
        this.load(this.index);
        this.load(this.index + 1);
        this.slides.forEach(function (slide, i) {
            var current = i === self.index;
            slide.classList.toggle('is-current', current);
            /* A slide nobody can see should not be read out or tabbed into. */
            slide.setAttribute('aria-hidden', current ? 'false' : 'true');
        });
        Array.prototype.forEach.call(this.dots.children, function (dot, i) {
            dot.setAttribute('aria-current', i === self.index ? 'true' : 'false');
        });
    };

    Gallery.prototype.step = function (by) {
        this.show(this.index + by);
        this.restart();
    };

    Gallery.prototype.pause = function () {
        if (this.timer) { window.clearInterval(this.timer); this.timer = null; }
    };

    Gallery.prototype.resume = function () {
        if (STILL || this.timer || this.held || !this.onScreen) { return; }
        var self = this;
        this.timer = window.setInterval(function () { self.show(self.index + 1); },
                                        this.interval);
    };

    Gallery.prototype.restart = function () {
        this.pause();
        this.resume();
    };

    function start() {
        Array.prototype.forEach.call(
            document.querySelectorAll('.gallery-rotate'),
            function (root) { new Gallery(root); });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
}());
