// DOM helpers shared by the pack's frontend scripts. No extension is registered
// here; ComfyUI loads the file like any other, which is harmless.

/** A DOM element with `props` assigned and `children` appended; every element of the pack's dialogs is built here. */
export function el(tag, props = {}, children = []) {
  const element = document.createElement(tag);
  Object.assign(element, props);
  element.append(...children);
  return element;
}

/**
 * Close a modal `dialog` on a click on its backdrop, which the browser reports with the dialog itself as
 * the target. A `click` lands on the nearest common ancestor of the press and the release, so a drag that
 * starts in a field and ends outside the box would look the same; the press has to be on the backdrop too.
 */
export function closeOnBackdropClick(dialog) {
  let pressedBackdrop = false;
  dialog.onpointerdown = (event) => {
    pressedBackdrop = event.target === dialog;
  };
  dialog.onclick = (event) => {
    if (pressedBackdrop && event.target === dialog) dialog.close();
  };
}
