"""
Test suite for scanner-fixer core image processing functions
"""

import pytest
import numpy as np
import cv2
from scanner_fixer import (
    detect_skew_angle,
    deskew,
    auto_crop,
    _normalize_rect_angle,
    _detect_minarect,
    _detect_hough,
)


class TestNormalizeRectAngle:
    """Tests for _normalize_rect_angle function"""
    
    def test_zero_angle(self):
        """Test with zero angle"""
        angle = _normalize_rect_angle(0.0, 100, 50)
        assert angle == 0.0
    
    def test_negative_angle(self):
        """Test with negative angle"""
        angle = _normalize_rect_angle(-45.0, 100, 50)
        # Should normalize to -45
        assert -45 <= angle <= 45
    
    def test_vertical_rectangle(self):
        """Test when width < height"""
        angle = _normalize_rect_angle(30.0, 50, 100)  # w < h
        # Should add 90 degrees
        assert 75 <= angle <= 125 or -180 <= angle <= -135


class TestDetectMinAreaRect:
    """Tests for _detect_minarect function"""
    
    def test_empty_image(self):
        """Test with empty/blank image"""
        blank = np.zeros((100, 100), dtype=np.uint8)
        angle, confidence = _detect_minarect(blank)
        assert confidence == 0.0
    
    def test_text_image(self):
        """Test with image containing text"""
        # Create a simple image with some text-like content
        img = np.zeros((100, 100), dtype=np.uint8)
        # Add some white pixels to simulate text
        img[30:70, 30:70] = 255
        angle, confidence = _detect_minarect(img)
        assert isinstance(angle, float)
        assert 0 <= confidence <= 1.0


class TestDetectHough:
    """Tests for _detect_hough function"""
    
    def test_empty_edges(self):
        """Test with image that has no edges"""
        blank = np.zeros((100, 100), dtype=np.uint8)
        angle, confidence = _detect_hough(blank)
        assert confidence == 0.0
    
    def test_line_image(self):
        """Test with image containing a line"""
        img = np.zeros((100, 100), dtype=np.uint8)
        # Draw a horizontal line
        img[50, 20:80] = 255
        angle, confidence = _detect_hough(img)
        assert isinstance(angle, float)


class TestDetectSkewAngle:
    """Tests for detect_skew_angle function"""
    
    def test_straight_image(self):
        """Test with perfectly straight image"""
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:, :] = (255, 255, 255)  # White background
        # Add some text
        img[30:70, 30:70] = (0, 0, 0)
        angle, confidence, method = detect_skew_angle(img)
        assert isinstance(angle, float)
        assert 0 <= confidence <= 1.0
        assert method in ["none", "minarect", "hough", "merged"]


class TestDeskew:
    """Tests for deskew function"""
    
    def test_zero_rotation(self):
        """Test with zero rotation angle"""
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:, :] = (255, 255, 255)
        result = deskew(img, 0.0)
        assert result.shape == img.shape
    
    def test_small_rotation(self):
        """Test with small rotation angle"""
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:, :] = (255, 255, 255)
        result = deskew(img, 5.0)
        assert result.shape == img.shape
    
    def test_white_background(self):
        """Test that deskew maintains white background"""
        img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = deskew(img, 10.0)
        # Check that corners are white (255)
        assert np.all(result[0, 0] == 255)
        assert np.all(result[0, -1] == 255)
        assert np.all(result[-1, 0] == 255)
        assert np.all(result[-1, -1] == 255)


class TestAutoCrop:
    """Tests for auto_crop function"""
    
    def test_white_image(self):
        """Test with all white image"""
        img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = auto_crop(img)
        # Should return original if no content detected
        assert result.shape[0] <= img.shape[0]
        assert result.shape[1] <= img.shape[1]
    
    def test_black_content_on_white(self):
        """Test with black content on white background"""
        img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        # Add black rectangle in center
        img[40:60, 40:60] = (0, 0, 0)
        result = auto_crop(img)
        # Should crop to the black content
        assert result.shape[0] < img.shape[0]
        assert result.shape[1] < img.shape[1]
    
    def test_margin_parameter(self):
        """Test with different margin values"""
        img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        img[40:60, 40:60] = (0, 0, 0)
        
        result_small = auto_crop(img, margin=5)
        result_large = auto_crop(img, margin=20)
        
        # Larger margin should result in larger output
        assert result_large.shape[0] >= result_small.shape[0]
        assert result_large.shape[1] >= result_small.shape[1]


class TestIntegration:
    """Integration tests for the full processing pipeline"""
    
    def test_full_pipeline(self):
        """Test complete processing workflow"""
        # Create a test image
        img = np.ones((200, 200, 3), dtype=np.uint8) * 255
        # Add some content
        img[80:120, 80:120] = (0, 0, 0)
        
        # Detect skew
        angle, confidence, method = detect_skew_angle(img)
        
        # Deskew
        deskewed = deskew(img, angle)
        
        # Auto crop
        cropped = auto_crop(deskewed)
        
        # Check results
        assert deskewed.shape == img.shape
        assert cropped.shape[0] <= img.shape[0]
        assert cropped.shape[1] <= img.shape[1]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
