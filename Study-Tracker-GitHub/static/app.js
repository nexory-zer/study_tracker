document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});


const photoField = document.querySelector('input[name="avatar"]');
const photoPreview = document.querySelector("#profile-avatar-preview");
if (photoField && photoPreview) {
  let previewUrl;
  const image = photoPreview.querySelector("img");
  const placeholder = photoPreview.querySelector(".avatar-person");
  const savedSource = image.getAttribute("src");
  photoField.addEventListener("change", () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    const file = photoField.files[0];
    if (file) {
      previewUrl = URL.createObjectURL(file);
      image.src = previewUrl;
      image.hidden = false;
      placeholder.hidden = true;
    } else {
      image.hidden = !savedSource;
      placeholder.hidden = Boolean(savedSource);
      if (savedSource) image.src = savedSource;
    }
  });
}
const achievements = document.getElementById("achievements");
if (achievements && location.hash === "#achievements") achievements.open = true;
