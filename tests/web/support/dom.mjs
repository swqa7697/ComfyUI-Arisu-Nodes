// Fake of the browser DOM surface load_image.js, cropper.js and settings_dialog.js touch: `document.createElement`,
// `document.body`, and `Image`. Elements are plain objects with a children list, so
// whatever a script assigns on one (className, textContent, handlers) is what a test
// reads back; layout is a stub a test overrides (`getBoundingClientRect`) and pointer
// capture a no-op. `Image` fires `onerror` for a URL containing "broken", and for a
// ".tif" file served whole (no `max=`: a format the browser cannot decode itself),
// and `onload` otherwise, on a microtask, the way a real load completes after `src` is
// set; a loaded image is 800 × 600 pixels.
export class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.parent = null;
    this.open = false;
    // a form control's value is an empty string until something is typed, never undefined
    if (this.tagName === 'INPUT') this.value = '';
  }
  append(...nodes) {
    for (const node of nodes) {
      node.parent = this;
      this.children.push(node);
    }
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this);
    this.parent = null;
  }
  setAttribute(name, value) {
    this[name] = value;
  }
  getBoundingClientRect() {
    return { left: 0, top: 0, width: this.naturalWidth ?? 0, height: this.naturalHeight ?? 0 };
  }
  setPointerCapture() {}
  releasePointerCapture() {}
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
    this.onclose?.();
  }
  focus() {}
}

class FakeImage extends FakeElement {
  constructor() {
    super('img');
  }
  set src(url) {
    this.url = url;
    const undecodable = url.includes('.tif') && !url.includes('max=');
    queueMicrotask(() => {
      if (url.includes('broken') || undecodable) return this.onerror?.();
      this.naturalWidth = 800;
      this.naturalHeight = 600;
      return this.onload?.();
    });
  }
  get src() {
    return this.url;
  }
}

export const body = new FakeElement('body');
globalThis.document = { body, createElement: (tag) => new FakeElement(tag) };
globalThis.Image = FakeImage;

/** Drop everything the previous test appended to the body. */
export function resetDom() {
  body.children = [];
}

/** Every element under `root`, depth first. */
export function descendants(root) {
  return root.children.flatMap((child) => [child, ...descendants(child)]);
}
