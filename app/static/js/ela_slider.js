class ElaComparisonSlider {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    if (!this.container) return;
    
    this.beforeImg = this.container.querySelector('.comparison-before');
    this.afterImg = this.container.querySelector('.comparison-after');
    this.handle = this.container.querySelector('.comparison-slider-handle');
    this.isDragging = false;
    this.currentMode = 'ela';
    this.imagesData = null;

    this.bindEvents();
  }

  setImages(imageData) {
    this.imagesData = imageData;
    if (!imageData) return;

    if (this.beforeImg) {
      this.beforeImg.src = imageData.original;
    }
    this.updateAfterImage();
    this.setSliderPosition(50);
  }

  setMode(mode) {
    this.currentMode = mode;
    this.updateAfterImage();
  }

  updateAfterImage() {
    if (!this.imagesData || !this.afterImg) return;
    if (this.currentMode === 'heatmap') {
      this.afterImg.src = this.imagesData.heatmap;
    } else {
      this.afterImg.src = this.imagesData.ela;
    }
  }

  bindEvents() {
    if (!this.handle || !this.container) return;

    const startDrag = (e) => {
      e.preventDefault();
      this.isDragging = true;
      document.addEventListener('mousemove', onDrag);
      document.addEventListener('mouseup', stopDrag);
      document.addEventListener('touchmove', onTouchDrag, { passive: false });
      document.addEventListener('touchend', stopDrag);
    };

    const onDrag = (e) => {
      if (!this.isDragging) return;
      this.updatePositionFromCoord(e.clientX);
    };

    const onTouchDrag = (e) => {
      if (!this.isDragging || !e.touches[0]) return;
      e.preventDefault();
      this.updatePositionFromCoord(e.touches[0].clientX);
    };

    const stopDrag = () => {
      this.isDragging = false;
      document.removeEventListener('mousemove', onDrag);
      document.removeEventListener('mouseup', stopDrag);
      document.removeEventListener('touchmove', onTouchDrag);
      document.removeEventListener('touchend', stopDrag);
    };

    this.handle.addEventListener('mousedown', startDrag);
    this.handle.addEventListener('touchstart', startDrag, { passive: false });

    this.container.addEventListener('click', (e) => {
      if (e.target.closest('.comparison-slider-button')) return;
      this.updatePositionFromCoord(e.clientX);
    });
  }

  updatePositionFromCoord(clientX) {
    const rect = this.container.getBoundingClientRect();
    let x = clientX - rect.left;
    let percentage = (x / rect.width) * 100;
    percentage = Math.max(0, Math.min(100, percentage));
    this.setSliderPosition(percentage);
  }

  setSliderPosition(percentage) {
    if (!this.handle || !this.afterImg) return;
    this.handle.style.left = `${percentage}%`;
    this.afterImg.style.clipPath = `polygon(${percentage}% 0, 100% 0, 100% 100%, ${percentage}% 100%)`;
  }
}

window.ElaComparisonSlider = ElaComparisonSlider;
