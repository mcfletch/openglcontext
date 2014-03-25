$.screenshots = function(url_list,screenshot_div,background_div) {
  var current_image;
  background_div.hide();
  var index=-1;
  
  var next_index = function() {
    var new_index = index + 1
    if (new_index>=url_list.length) {
      new_index = 0;
    }
    return new_index;
  }
  var load_next = function() {
    var img = $('<img alt="Screenshot" />');
    img.attr( 'src', url_list[next_index()] );
    background_div.empty();
    background_div.append( img );
  };
  
  var show_loaded = function() {
    var loaded = background_div.find( 'img' );
    if (loaded.length) {
        current_image = loaded;
        var target_width = screenshot_div.width();
        var target_height = screenshot_div.height();
        var target_ratio = target_height/target_width;
        var width, height, ratio;
        width = loaded[0].naturalWidth;
        height = loaded[0].naturalHeight;
        if ((! width) || (! height)) {
            return;
        }
        ratio = height/width;
        if (ratio > target_ratio) {
            // Image is narrower than target...
            loaded.css( {
                'height': target_height,
                'width': target_height / ratio
            });
        } else {
            loaded.css( {
                'height': target_width * ratio,
                'width': target_width
            });
        }
        screenshot_div.empty();
        loaded.hide();
        screenshot_div.append( loaded );
    }
    load_next();
    loaded.show( 250 );
    loaded.click( next_image );
  };
  
  var next_image = function() {
    index = next_index();
    if (current_image && current_image.length) {
        current_image.hide( 250, show_loaded );
    } else {
        show_loaded();
    }
  }
  window.setInterval( next_image, 5000 );
  next_image();
};
