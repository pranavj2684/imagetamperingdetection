# imagetamperingdetection
An Image Tampering Detection and Localization using MATLAB. 
IMAGE TAMPERING DETECTION AND LOCALIZATION USING ELA (Error-Level Analysis)

Step 1:
Reading and extracting Metadata of an Image 
Step 2: (Error Level Analysis)
Error Level Analysis (ELA) permits identifying areas within an image that are at different compression levels. With JPEG images, the entire picture should be at roughly the same level. If a section of the image is at a significantly different error level, then it likely indicates a digital modification.
ELA highlights differences in the JPEG compression rate. Regions with uniform colouring, like a solid blue sky or a white wall, will likely have a lower ELA result (darker colour) than high-contrast edges. The things to look for: 

Edges:	
Similar edges should have similar brightness in the ELA result. All high-contrast edges should look similar to each other, and all low-contrast edges should look similar. With an original photo, low-contrast edges should be almost as bright as high-contrast edges.
Textures:   
Similar textures should have similar colouring under ELA. Areas with more surface detail, such as a close-up of a basketball, will likely have a higher ELA result than a smooth surface.

Surfaces:
	Regardless of the actual colour of the surface, all flat surfaces should have about the same colouring under ELA.

Look around the picture and identify the different high-contrast edges, low-contrast edges, surfaces, and textures. Compare those areas with the ELA results. If there are significant differences, then it identifies suspicious areas that may have been digitally altered. 

Resaving a JPEG removes high-frequencies and results in less differences between high-contrast edges, textures, and surfaces. A very low quality JPEG will appear very dark. 

Scaling a picture smaller can boost high-contrast edges, making them brighter under ELA. Similarly, saving a JPEG with an Adobe product will automatically sharpen high-contrast edges and textures, making them appear much brighter than low-texture surfaces.
Disadvantages:
•	A single pixel change, or minor colour adjustment, may not generate a noticeable change in the ELA.
•	Since JPEG operates on a grid, a change to any part of the grid will likely impact the entire grid square. You may not be able to identify exactly which pixel in the grid was modified.
•	JPEG uses the YUV colour space. High contrast colors in the same grid, such as black and white, orange and blue, or green and purple (opposite ends of the YUV colour space), will usually generate higher ELA values than similar colours in the same grid.
•	ELA only identifies what regions have different compression levels. It does not identify sources. If a lower quality image is spliced into a higher quality picture, then the lower quality image may appear as a darker region.
•	Scaling, recolouring, or adding noise to an image will modify the entire image, creating a higher error level potential.
•	If an image is resaved multiple times, then it may be entirely at a minimum error level, where more resaves do not alter the image. In this case, the ELA will return a black image and no modifications can be identified using this algorithm.
•	With Photoshop, the simple act of saving the picture can auto-sharpen textures and edges, creating a higher error level potential. This artifact does not identify intentional modification; it identifies that an Adobe product was used. (Remember: if someone needs to download a picture from their camera or resize a picture for the web, they are just as likely to reach for Photoshop as they are to use any other tool.) Technically, ELA appears as a modification because Adobe automatically performed a modification, but the modification was not necessarily intentional by the user.
•	As mentioned above, rainbowing is not exclusive to Photoshop. The open source GIMP drawing program may introduce a little rainbowing and some high quality photos may contain rainbowing.
•	NOTE: ELA is only one algorithm. The interpretation of results may be inconclusive. It is important to validate findings with other analysis techniques and algorithms. (To Know more visit this link: http://fotoforensics.com/tutorial-ela.php)

Step 3:  Calculating Luminosity of RGB channel of Entire image
Here the luminosity i.e. The intensity of Red green and blue of all the pixels in the entire image is calculated. Here entire image is iterated and maximum value is retrieved from the RGB vectors of Image.
Step 4: Performing 2-D Adaptive Noise - removal Filtering
wiener2 lowpass filters an intensity image that has been degraded by constant power additive noise. wiener2 uses a pixel-wise adaptive Wiener method based on statistics estimated from a local neighbourhood of each pixel.
Step 5: Creating Morphological Structuring Element and recreating morphological image using ‘bothat’ and ‘tophat’
operations
Syntax:
SE = strel(shape,parameters)
Description:
SE = strel(shape,parameters) creates a structuring element, SE, of the type specified by shape. Here the Morphological opening and closing of an image is calculated using ‘bothat’ and ‘tophat’ functions.
