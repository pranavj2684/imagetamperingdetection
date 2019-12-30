 function ela = generate_ela(filename,qf)
    if nargin > 2 | nargin < 2
        error('usage: generate_ela(filename)');
    end
    img_orig = filename;
    ula = imfinfo(img_orig);
    disp(ula);
    disp(ula.Filename);
    filesize_orig = ula.FileSize;
    
    originalSize = filesize_orig/1024;
    disp(originalSize);
    
    orig = imread(img_orig);
    
    %msgbox(filename);
    tempfile = 'H:\temp.jpg';
    imwrite(orig,tempfile,'jpeg','Quality',qf);
    temp = imread(tempfile);
    %delete(tempfile);
    idiff = uint8(abs(double(orig)-double(temp))*30);   
    me = max(max(max(idiff)));
    idiff = uint8(double(idiff)*255/double(me));
    
    Img = .299*idiff(:,:,1)...
            +.587*idiff(:,:,2)...
            +.114*idiff(:,:,3);
    answer = max(Img(:));
    disp(answer);
    %if(answer >= 250 )
    %    msgbox(sprintf('Intensity = %g',answer),'Forgery Detected','warn');
    %end    
    k = wiener2(im2double(rgb2gray(idiff)),[5 5]);

    figure; 
    imshow(idiff);
    figure;
    imshow(k);
    
    %Morphological operation dilation followed by erosion%
    se = strel('disk',3);
    contrastfiltered = ...
        (orig+imtophat(orig,se))-imbothat(orig,se); %Returns the image minus the morphological closing of the image%
    Ml= double(contrastfiltered);
    figure;
    imshow(Ml);
    
    
    BW2 = bwmorph(255*double(rgb2gray(orig)),'remove');
    
    cc = bwconncomp(4);
    disp(cc);
    labeled = labelmatrix(cc);
    eul = bweuler(BW2,4);
    disp(eul);
    
    figure;
    imshow(BW2);    
    
    
    destinationFolder = 'F:\Matlab\Matlab Codes\copy_move_forgery\Results';
    if ~exist(destinationFolder,'dir')
        mkdir(destinationFolder,'dir');
    end
    
    basename1 = '1.jpg';
    basename2 = '2.jpg';
    basename3 = '3.jpg';
    basename4 = '4.jpg';
    fullfileName = fullfile(destinationFolder,basename1);
    imwrite(idiff,fullfileName);
    fullfileName = fullfile(destinationFolder,basename2);
    imwrite(k,fullfileName);
    fullfileName = fullfile(destinationFolder,basename3);
    imwrite(Ml,fullfileName);
    fullfileName = fullfile(destinationFolder,basename4);
    imwrite(BW2,fullfileName);
    %figure;
    %imshow(kaverage);
    
    
end